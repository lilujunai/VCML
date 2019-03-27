special_tokens = {
    '<NULL>': 0,
    '<START>': 1,
    '<END>': 2,
    '<UNK>': 3,
}
import numpy as np


def build_tokenMap(obj, vocabulary, add_special_tokens=False):
    tokenMap = {}
    if add_special_tokens:
        for l in vocabulary.values():
            l += special_tokens
    for c in vocabulary.keys():
        item = vocabulary[c]
        tokenMap[c+'2idx'], tokenMap['idx2'+c] =\
            ({y: i for i, y in enumerate(item)}, item)
    for k, v in tokenMap.items():
        setattr(obj, k, v)


def tokenize(s, delim=' ',
             add_start_token=True, add_end_token=True,
             punct_to_keep=None, punct_to_remove=None):
    if punct_to_keep is not None:
        for p in punct_to_keep:
            s = s.replace(p, '%s%s' % (delim, p))

    if punct_to_remove is not None:
        for p in punct_to_remove:
            s = s.replace(p, '')

    tokens = s.split(delim)
    if add_start_token:
        tokens.insert(0, '<START>')
    if add_end_token:
        tokens.append('<END>')
    return tokens


def encode_question(question, token_to_idx, allow_unk=False, length=0):
    seq_tokens = tokenize(question, punct_to_keep=[';', ',', '?', '.'])
    seq_idx = []
    for token in seq_tokens:
        if token not in token_to_idx:
            if allow_unk:
                token = '<UNK>'
            else:
                raise KeyError('Token "%s" not in vocab' % token)
        seq_idx.append(token)
    seq_idx += ['<NULL>' for i in range(length-len(seq_idx))]
    seq_idx = [token_to_idx[x] for x in seq_idx]
    return np.array(seq_idx)

def filter_questions(question, mode):
    if mode == 'None':
        return True
    elif mode == 'existance':
        for op in question['semantic']:
            if op['operation'] not in ['exist', 'select']:
                return False
    return True
