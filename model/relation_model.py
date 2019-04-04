#!/usr/bin/env python
# coding=utf-8

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.utils.data
#from numpy import random

class RelationModel(nn.Module):
    def __init__(self, args, info=None):
        super(RelationModel, self).__init__()
        self.args = args
        self.info = info

        self.attribute_embeddingIn = nn.Embedding(args.num_attributes, args.embed_dim)
        self.attribute_embeddingOut = nn.Embedding(args.num_attributes, args.embed_dim)
        self.attribute_embeddingId = nn.Embedding(args.num_attributes, args.identity_dim)
        self.feature_linearIn = nn.Linear(args.feature_dim, args.embed_dim)
        self.feature_linearOut = nn.Linear(args.feature_dim, args.embed_dim)
        self.feature_linearId = nn.Linear(args.feature_dim, args.identity_dim)
        self.concept_embeddingIn = nn.Embedding(args.max_concepts, args.embed_dim)
        self.concept_embeddingOut = nn.Embedding(args.max_concepts, args.embed_dim)
        self.concept_embeddingId = nn.Embedding(args.max_concepts, args.identity_dim)

        self.embed_init = nn.Parameter(torch.randn(args.embed_dim))
        self.identity_init = nn.Parameter(torch.randn(args.identity_dim))
        self.attention_init = nn.Parameter(torch.randn(args.attention_dim) + 1)

        def build_mlp(dim_in, dim_hidden, dim_out, name):
            linear1 = nn.Linear(dim_in, dim_hidden)
            linear2 = nn.Linear(dim_hidden, dim_out)
            setattr(self, name+'_linear1', linear1)
            setattr(self, name+'_linear2', linear2)
            return lambda x: linear2(torch.relu(linear1(x)))

        self.axon_mlp = build_mlp(args.attention_dim+args.identity_dim,
                                  args.hidden_dim,
                                  args.attention_dim,
                                  'axon')
        self.meta_mlp = build_mlp(args.embed_dim+args.attention_dim,
                                  args.hidden_dim,
                                  args.attention_dim,
                                  'meta')

    def forward(self, data):
        args = self.args
        info = self.info
        batch_size = data.answer.shape[0]
        num_objects = max([data.scene[i].shape[0] for i in range(batch_size)])
        dim_concept = num_objects + args.max_concepts

        #is_mode = (data.program[:, :, 0] == info.protocol['operations', 'mode']).astype(int)
        is_insert = (data.program[:, :, 0] == info.protocol['operations', 'insert']).astype(int)
        is_transfer = (data.program[:, :, 0] == info.protocol['operations', 'transfer']).astype(int)

        def embed_without_bg(embedding, x):
            non_bg = (x != -1).astype(int)
            x = torch.LongTensor(x+1).to(info.device)
            non_bg = torch.Tensor(non_bg).to(info.device)
            return (embedding(x) * non_bg[:,:,None]).sum(1)

        objectsIn = self.embed_init[None, None].repeat((batch_size, num_objects, 1))
        objectsOut = self.embed_init[None, None].repeat((batch_size, num_objects, 1))
        objectsId = self.identity_init[None, None].repeat((batch_size, num_objects, 1))
        for i in range(batch_size):
            num_here = data.scene[i].shape[0]
            if data.scene.dtype.name == 'int64':
                objectsIn[i, :num_here] =\
                    embed_without_bg(self.attribute_embeddingIn, data.scene[i])
                objectsOut[i, :num_here] =\
                    embed_without_bg(self.attribute_embeddingOut, data.scene[i])
                objectsId[i, :num_here] =\
                    embed_without_bg(self.attribute_embeddingId, data.scene[i])
            else:
                objectsIn[i, :num_here] = self.feature_linearIn(
                    torch.Tensor(data.scene[i]).to(info.device))
                objectsOut[i, :num_here] = self.feature_linearOut(
                    torch.Tensor(data.scene[i]).to(info.device))
                objectsId[i, :num_here] = self.feature_linearId(
                    torch.Tensor(data.scene[i]).to(info.device))

        dendron = torch.cat((self.concept_embeddingIn.weight[None].repeat((batch_size, 1, 1)), objectsIn), 1)
        axon = torch.cat((self.concept_embeddingOut.weight[None].repeat((batch_size, 1, 1)), objectsOut), 1)
        identity = torch.cat((self.concept_embeddingId.weight[None].repeat((batch_size, 1, 1)), objectsId), 1)
        meta = self.attention_init[None].repeat((batch_size, 1))

        attention = (self.attention_init*0)[None, None].repeat((batch_size, dim_concept, 1))
        arguments = self.concept_embeddingOut(torch.LongTensor(data.program[:, :, 1]).to(info.device))

        max_program_length = data.program.shape[1]
        history = []
        for i in range(max_program_length):
            '''
            attention_scalar = attention.abs().sum(2)
            normalize = lambda x: x/x.sum()
            selected = np.stack([
                random.choice(np.arange(args.max_concepts),
                              args.size_attention,
                              p=normalize(attention_scalar[i, :args.max_concepts]\
                                          .cpu().detach().numpy()))
                for i in range(batch_size)
            ])
            def get_selected(original):
                return torch.stack([
                    original[i, selected[i]] for i in range(batch_size)
                ])
            attention_selected = get_selected(attention)
            thoughtOut_selected = get_selected(thoughtOut)
            '''

            #is_mode_ = torch.Tensor(is_mode[:, i, None]).to(info.device)
            is_insert_ = torch.Tensor(is_insert[:, i, None, None]).to(info.device)
            is_transfer_ = torch.Tensor(is_transfer[:, i, None, None]).to(info.device)

            #new_meta = self.meta_mlp(torch.cat((meta, arguments[:, i]), 1))
            #meta = is_mode_ * new_meta + (1-is_mode_) * meta
            meta_broadcast = meta[:, None].repeat((1, dim_concept, 1))
            attention_insert = meta_broadcast * (arguments[:, i, None] * axon).mean(2)[:, :, None]

            message_transfer = torch.Tensor(axon.shape[:2] + (args.identity_dim + args.attention_dim,))
            activated_axon = attention.mean(2)[:, :, None] * axon

            identity_attention = torch.cat([identity, attention], 2)
            for j in range(batch_size):
                input_weight = torch.matmul(dendron[j], activated_axon[j].transpose(1, 0))
                input_weight = torch.clamp(input_weight / dim_concept, -2, 2)
                message_transfer[j] = torch.matmul(input_weight, identity_attention[j]) / dim_concept
            message_transfer = message_transfer.to(info.device)
            attention_transfer = self.axon_mlp(message_transfer) + message_transfer[:, :, args.identity_dim:]
            #attention_transfer = message_transfer[:, :, args.embed_dim:]

            attention = attention + is_insert_ * attention_insert + is_transfer_ * attention_transfer
            #attention = is_insert_ * attention_insert + is_transfer_ * attention_transfer
            attention = torch.relu(attention)
            history.append(attention)

        output_length = attention.mean(2)
        output_softmax = F.log_softmax(output_length, 1)
        return output_softmax, torch.stack(history)
