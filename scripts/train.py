import sys
setattr(sys, 'info', None)
setattr(sys, 'args', None)
from IPython.core import ultratb
sys.excepthook = ultratb.FormattedTB(mode='Plain',
                                     color_scheme='Linux', call_pdb=1)
import os
if os.getcwd().endswith('scripts'):
    sys.path.append('../')
from config import Config, Info
args = Config()
info = Info()

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from IPython import embed
import torch
import torch.nn.functional as F
from torch.autograd import Variable
from dataset import visual_dataset, question_dataset
from dataset.tools import protocol, dataset_scheduler
from model.relation_model import RelationModel
from model.uEmbedding_model import UEmbedding
from model.hEmbedding_model import HEmbedding
from model.classification import Classification
from utils.recording import Recording
from utils.common import tqdm, contains, equal_ratio, equal_items, recall
from utils.basic import init_seed, save_log
import numpy as np

def run_batch(data):
    output, target, history, penalty_loss, types = info.model(data)
    output = info.to(output)
    conceptual = np.array(list(map(lambda x: contains(x, args.conceptual_subtasks),
                                   types.tolist()))).astype(float)
    weight = info.to(torch.Tensor(conceptual * args.conceptual_weight
                                  + 1 - conceptual))

    if info.new_torch:
        losses = info.loss_fn(output, target, reduction='none')
        answers = output.argmax(1)
    else:
        losses = info.loss_fn(output, Variable(target), reduce=False)
        weight = Variable(weight)
        answers = output.data.max(1)[1]

    accuracy = equal_ratio(answers, target)

    loss = (weight * (losses + penalty_loss * args.penalty)).sum()
    output = {'loss': loss, 'accuracy': accuracy,
              }

    if 'yes' in info.question_dataset.answers:
        yes = equal_ratio(answers, info.protocol['concepts', 'yes'])
        no = equal_ratio(answers, info.protocol['concepts', 'no'])
        output.update({'yes': yes, 'no': no})

    yes_items = equal_items(answers, info.protocol['concepts', 'yes'])
    no_items = equal_items(answers, info.protocol['concepts', 'no'])
    right_items = equal_items(answers, target)
    question_types = info.question_dataset.types
    for t in question_types:
        type_items = equal_items(types, t)
        if type_items.sum() > 0:
            for select_items, select_name in\
                    ((yes_items, 'yes'), (no_items, 'no'), (right_items, 'right')):
                output['{}_{}'.format(t, select_name)] = recall(select_items, type_items)

    return output


def train_epoch():
    info.model.train()
    info.pbars[0].write('epoch {}'.format(info.epoch))
    recording = info.train_recording
    for data in tqdm(info.train):
        info.optimizer.zero_grad()
        recording.update(run_batch(data))
        recording.previous['loss'].backward(retain_graph=False)
        info.optimizer.step()

        info.pbars[1].set_description(str(recording)[:70])

    info.pbars[0].write('[TRAIN]\t' + recording.strings()[0][:100])


def val_epoch():
    info.model.eval()
    recording = info.val_recording
    with torch.no_grad():
        for data in tqdm(info.val):
            recording.update(run_batch(data))

            info.pbars[1].set_description(str(recording)[:70])

    info.pbars[0].write('[VAL]\t%s' % recording.strings()[0][:100])

def init():
    if args.random_seed:
        init_seed(args.random_seed)
    info.model.init()
    info.to(info.model)
    info.train_recording = Recording(name='train', mode='decaying')
    info.val_recording = Recording(name='val', mode='average')
    info.dataset_scheduler = dataset_scheduler.DatasetScheduler()

def run():
    for info.epoch in tqdm(range(1, args.epochs + 1)):

        if args.visualize_dir and not args.silent:
            if not isinstance(info.model, Classification):
                info.model.visualize_embedding(args.visualize_relation)
                info.model.visualize_logit()
            info.train_recording.visualize()
            info.val_recording.visualize()

        train_epoch()
        if not args.no_validation:
            val_epoch()

        info.scheduler.step(info.train_recording.data['loss'])
        info.dataset_scheduler.step(info.train_recording.data['accuracy'])

        info.val_recording.clear()

        if not args.silent:
            info.model.save(args.name)
            save_log(os.path.join(args.log_dir, args.name+'.pkl'),
                    info.val_recording.history,
                    args.__dict__)

def main():
    info.embed = embed
    info.protocol = protocol.Protocol(args.allow_output_protocol, args.protocol_file)
    info.plt = plt
    info.np = np

    if args.random_seed:
        init_seed(args.random_seed)

    info.dataset_all = dataset_scheduler.\
        build_incremental_training_datasets(visual_dataset.Dataset,
                                            question_dataset.Dataset)
    args.names = info.vocabulary.concepts

    if args.model == 'relation_model':
        info.model = RelationModel()
    elif args.model == 'u_embedding':
        info.model = UEmbedding()
    elif args.model in ['h_embedding_mul', 'h_embedding_add',
                        'h_embedding_add2']:
        info.model = HEmbedding()
    info.loss_fn = F.nll_loss

    args.print()
    info.pbars = []
    info.log = {}

    init()
    run()
    embed()

if __name__ == '__main__':
    main()
