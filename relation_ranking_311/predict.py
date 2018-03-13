import os
import sys
import numpy as np
import torch
import pickle

from args import get_args
from model import RelationRanking
from seqRankingLoader import *
sys.path.append('../tools')
import virtuoso

# please set the configuration in the file : args.py
args = get_args()
# set the random seed for reproducibility
torch.manual_seed(args.seed)
if not args.cuda:
    args.gpu = -1
if torch.cuda.is_available() and args.cuda:
    print("Note: You are using GPU for training")
    torch.cuda.set_device(args.gpu)
    torch.cuda.manual_seed(args.seed)
if torch.cuda.is_available() and not args.cuda:
    print("Warning: You have Cuda but do not use it. You are using CPU for training")


if not args.trained_model:
    print("ERROR: You need to provide a option 'trained_model' path to load the model.")
    sys.exit(1)

# load word vocab for questions, relation vocab for relations
word_vocab = torch.load(args.vocab_file)
print('load word vocab, size: %s' % len(word_vocab))
rel_vocab = torch.load(args.rel_vocab_file)
print('load relation vocab, size: %s' %len(rel_vocab))

os.makedirs(args.results_path, exist_ok=True)

# load the model
model = torch.load(args.trained_model, map_location=lambda storage,location: storage.cuda(args.gpu))

def evaluate(dataset = args.test_file, tp = 'test'):

    # load batch data for predict
    data_loader = SeqRankingSepratedLoader(dataset, args.gpu)
    print('load %s data, batch_num: %d\tbatch_size: %d'
            %(tp, data_loader.batch_num, data_loader.batch_size))

    model.eval();
    n_correct = 0

    for data_batch_idx, data_batch in enumerate(data_loader.next_batch(shuffle=False)):
#        if data_batch_idx > 1:break
        pos_score1, pos_score2, neg_score1, neg_score2 = model(data_batch)
        neg_size, batch_size = pos_score1.size()
        n_correct += (torch.sum(torch.gt(pos_score1+pos_score2, neg_score1+neg_score2), 0).data ==
                      neg_size).sum()

        seqs, seq_len, pos_rel1, pos_rel2, neg_rel1, neg_rel2 = data_batch
        seqs_trans = seqs.cpu().data.numpy()
        pos_rel_trans1 = pos_rel1.cpu().data.numpy()
        pos_rel_trans2 = pos_rel2.cpu().data.numpy()
        neg_rel_trans1 = neg_rel1.cpu().data.numpy()
        neg_rel_trans2 = neg_rel2.cpu().data.numpy()
        neg_score = (neg_score1+neg_score2).cpu().data.numpy()
        pred_rel = np.argmax(neg_score, axis=0)
        pred_rel_scores = np.max(neg_score, axis=0)
        pos_score = (pos_score1+pos_score2).cpu().data.numpy()
        for j in range(batch_size):
            question = ' '.join(word_vocab.convert_to_word(seqs_trans[j]))
            pos_rel_1 = rel_vocab[0].index2word[pos_rel_trans1[j]]
            pos_rel_2 = rel_vocab[1].index2word[pos_rel_trans2[j]]
            neg_rel_1 = rel_vocab[0].index2word[neg_rel_trans1[pred_rel[j]][j]]
            neg_rel_2 = rel_vocab[1].index2word[neg_rel_trans2[pred_rel[j]][j]]
#            print(question)
#            print(pos_rel_1+'.'+pos_rel_2, pos_score[0][j])
#            print(neg_rel_1+'.'+neg_rel_2, pred_rel_scores[j])

    total = data_loader.batch_num*data_loader.batch_size
    accuracy = 100. * n_correct / (total)
    print("%s\taccuracy: %8.6f\tcorrect: %d\ttotal: %d" %(tp, accuracy, n_correct, total))
    print("-" * 80)

def rel_pruned(neg_score, data):
    neg_rel = data.cand_rel
    pred_rel_scores = sorted(zip(neg_rel, neg_score), key=lambda i:i[1], reverse=True)
    pred_rel = pred_rel_scores[0][0]
    pred_sub = []
    for i, rels in enumerate(data.sub_rels):
        if pred_rel in rels:
            pred_sub.append(data.cand_sub[i])
    return pred_rel, pred_rel_scores, pred_sub


def predict(tp='test', write_res=args.write_result, write_score=args.write_score):
    # load batch data for predict
    qa_pattern_file = '../data/QAData.label.%s.pkl' %tp
    data_loader = CandidateRankingLoader(qa_pattern_file, word_vocab, rel_vocab, args.gpu)
    print('load %s data, batch_num: %d\tbatch_size: %d' %(tp, data_loader.batch_num, 1))
    if write_res:
        results_file = open(os.path.join(args.results_path, '%s-pred_rel-wrong.txt' %tp), 'w')
        results_all_file = open(os.path.join(args.results_path, '%s-results-all.txt' %tp), 'w')
    pred_rel_file = open(os.path.join(args.results_path, '%s-rel_results.txt' %tp), 'w')

    model.eval()
    total = 0
    rel_scores = []
    n_correct = 0
    n_rel_correct = 0
    n_sub_recall = 0
    n_single_correct = 0
    for data_batch in data_loader.next_question():
        data = data_batch[-1]
        if data.subject not in data.cand_sub: # cand_sub错的就不用管了
            continue
        total += 1

        pos_score1, pos_score2, neg_score1, neg_score2 = model(data_batch[:-1])
        neg_score = (neg_score1+neg_score2).data.squeeze().cpu().numpy()

        if write_score:
            rel_scores.append(neg_score)
#            score_file.write('%s\n' %(' '.join(neg_score.astype('str'))))

        pred_rel, pred_rel_scores, pred_sub = rel_pruned(neg_score, data)

        if pred_rel == data.relation:
            pred_rel_file.write('1\n')
            n_rel_correct += 1
            if data.subject in pred_sub:
                n_sub_recall += 1
                if pred_sub[0] == data.subject:
                    n_correct += 1
                    if len(pred_sub) == 1:
                        n_single_correct += 1  # sub和rel都预测正确且唯一的个数
        else:
            pred_rel_file.write('0\n')
        '''
        elif write_res:
            results_file.write('%s\n' %(data.question))
            results_file.write('%s\t%s\n' %(data.relation, pred_rel_scores[:3]))

        if write_res:
            results_all_file.write('%s\n' %(data.question))
            results_all_file.write('%s\t%s\t%s\n' %(data.subject, pred_sub[:3], data.subject in pred_sub))
            results_all_file.write('%s\t%s\n' %(data.relation, pred_rel_scores[:3]))
        '''

    if write_score:
        score_file = open(os.path.join(args.results_path, 'score-rel-%s.pkl' %tp), 'wb')
        pickle.dump(rel_scores, score_file)

    accuracy = 100. * n_correct / total
    rel_acc = 100. * n_rel_correct / total
    sub_recall = 100. * n_sub_recall / total
    single_acc = 100. * n_single_correct / total
    print("%s\taccuracy: %8.6f\tcorrect: %d\ttotal: %d" %(tp, accuracy, n_correct, total))
    print('rel_acc: ', rel_acc, n_rel_correct)
    print('recall: ', sub_recall, n_sub_recall)
    print('single_acc: ', single_acc, n_single_correct)
    print("-" * 80)

if args.predict:
    predict('valid')
    predict('test')
    predict('train')
else:
    evaluate(args.valid_file, "valid")
    evaluate(args.test_file, "test")
    evaluate(args.train_file, 'train')
