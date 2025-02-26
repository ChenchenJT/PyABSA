# -*- coding: utf-8 -*-
# file: train_atepc.py
# time: 2021/5/26 0026
# author: yangheng <yangheng@m.scnu.edu.cn>
# github: https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.


import os
import random
import pickle
import tqdm
import time

import numpy as np
import torch
import torch.nn.functional as F
from seqeval.metrics import classification_report
from sklearn.metrics import f1_score
from torch.utils.data import (DataLoader, RandomSampler, SequentialSampler, TensorDataset)
from transformers import AutoTokenizer
from transformers import AutoModel

from ..dataset_utils.data_utils_for_training import ATEPCProcessor, convert_examples_to_features
from pyabsa.utils.logger import get_logger


class Instructor:

    def __init__(self, opt):
        self.opt = opt
        self.logger = opt.logger

        if os.path.exists(self.opt.dataset_path):
            log_name = '{}_{}_srd{}_unknown'.format(self.opt.model_name, self.opt.lcf, self.opt.SRD)
        else:
            log_name = '{}_{}_srd{}_{}'.format(self.opt.model_name, self.opt.lcf, self.opt.SRD, self.opt.dataset_path)
        self.logger = get_logger(os.getcwd(), log_name=log_name, log_type='training_tutorials')
        if opt.use_bert_spc:
            self.logger.info('Warning, the use_bert_spc parameter is disabled in '
                             'extracting aspect and predicting sentiment, reset use_bert_spc=False and go on... ')
            opt.use_bert_spc = False
        import warnings
        warnings.filterwarnings('ignore')
        if self.opt.gradient_accumulation_steps < 1:
            raise ValueError("Invalid gradient_accumulation_steps parameter: {}, should be >= 1".format(
                self.opt.gradient_accumulation_steps))

        self.opt.batch_size = self.opt.batch_size // self.opt.gradient_accumulation_steps

        random.seed(self.opt.seed)
        np.random.seed(self.opt.seed)
        torch.manual_seed(self.opt.seed)
        torch.cuda.manual_seed(self.opt.seed)

        if self.opt.model_path_to_save and not os.path.exists(self.opt.model_path_to_save):
            os.makedirs(self.opt.model_path_to_save)

        self.optimizers = {
            'adam': torch.optim.Adam,
            'adamw': torch.optim.AdamW
        }

        self.tokenizer = AutoTokenizer.from_pretrained(self.opt.pretrained_bert_name, do_lower_case=True)
        bert_base_model = AutoModel.from_pretrained(self.opt.pretrained_bert_name)
        processor = ATEPCProcessor(self.tokenizer)
        self.label_list = processor.get_labels()
        num_labels = len(self.label_list) + 1

        bert_base_model.config.num_labels = num_labels

        self.train_examples = processor.get_train_examples(self.opt.dataset_file['train'], 'train')
        self.num_train_optimization_steps = int(
            len(self.train_examples) / self.opt.batch_size / self.opt.gradient_accumulation_steps) * self.opt.num_epoch
        train_features = convert_examples_to_features(self.train_examples, self.label_list, self.opt.max_seq_len,
                                                      self.tokenizer, self.opt)
        all_spc_input_ids = torch.tensor([f.input_ids_spc for f in train_features], dtype=torch.long)
        all_input_mask = torch.tensor([f.input_mask for f in train_features], dtype=torch.long)
        all_segment_ids = torch.tensor([f.segment_ids for f in train_features], dtype=torch.long)
        all_label_ids = torch.tensor([f.label_id for f in train_features], dtype=torch.long)
        all_valid_ids = torch.tensor([f.valid_ids for f in train_features], dtype=torch.long)
        all_lmask_ids = torch.tensor([f.label_mask for f in train_features], dtype=torch.long)
        all_polarities = torch.tensor([f.polarity for f in train_features], dtype=torch.long)
        lcf_cdm_vec = torch.tensor([f.lcf_cdm_vec for f in train_features], dtype=torch.float32)
        lcf_cdw_vec = torch.tensor([f.lcf_cdw_vec for f in train_features], dtype=torch.float32)

        train_data = TensorDataset(all_spc_input_ids, all_segment_ids, all_input_mask, all_label_ids,
                                   all_polarities, all_valid_ids, all_lmask_ids, lcf_cdm_vec, lcf_cdw_vec)

        train_sampler = SequentialSampler(train_data)
        self.train_dataloader = DataLoader(train_data, sampler=train_sampler, batch_size=self.opt.batch_size)

        if 'test' in self.opt.dataset_file:
            eval_examples = processor.get_test_examples(self.opt.dataset_file['test'], 'test')
            eval_features = convert_examples_to_features(eval_examples, self.label_list, self.opt.max_seq_len,
                                                         self.tokenizer, self.opt)
            all_spc_input_ids = torch.tensor([f.input_ids_spc for f in eval_features], dtype=torch.long)
            all_input_mask = torch.tensor([f.input_mask for f in eval_features], dtype=torch.long)
            all_segment_ids = torch.tensor([f.segment_ids for f in eval_features], dtype=torch.long)
            all_label_ids = torch.tensor([f.label_id for f in eval_features], dtype=torch.long)
            all_polarities = torch.tensor([f.polarity for f in eval_features], dtype=torch.long)
            all_valid_ids = torch.tensor([f.valid_ids for f in eval_features], dtype=torch.long)
            all_lmask_ids = torch.tensor([f.label_mask for f in eval_features], dtype=torch.long)
            lcf_cdm_vec = torch.tensor([f.lcf_cdm_vec for f in eval_features], dtype=torch.float32)
            lcf_cdw_vec = torch.tensor([f.lcf_cdw_vec for f in eval_features], dtype=torch.float32)
            eval_data = TensorDataset(all_spc_input_ids, all_segment_ids, all_input_mask, all_label_ids, all_polarities,
                                      all_valid_ids, all_lmask_ids, lcf_cdm_vec, lcf_cdw_vec)
            # all_tokens = [f.tokens for f in eval_features]

            eval_sampler = RandomSampler(eval_data)
            self.eval_dataloader = DataLoader(eval_data, sampler=eval_sampler, batch_size=self.opt.batch_size)

        # init the model behind the convert_examples_to_features function in case of updating polarities_dim

        self.model = self.opt.model(bert_base_model, opt=self.opt)
        self.model.to(self.opt.device)
        param_optimizer = list(self.model.named_parameters())
        no_decay = ['bias', 'LayerNorm.bias', 'LayerNorm.weight']
        self.optimizer_grouped_parameters = [
            {'params': [p for n, p in param_optimizer if not any(nd in n for nd in no_decay)],
             'weight_decay': self.opt.l2reg},
            {'params': [p for n, p in param_optimizer if any(nd in n for nd in no_decay)],
             'weight_decay': self.opt.l2reg}
        ]
        self.optimizer = self.optimizers[self.opt.optimizer](self.optimizer_grouped_parameters,
                                                             lr=self.opt.learning_rate,
                                                             weight_decay=self.opt.l2reg)
        for arg in vars(self.opt):
            self.logger.info('>>> {0}: {1}'.format(arg, getattr(self.opt, arg)))


    def train(self):

        self.logger.info("***** Running training for Aspect Term Extraction *****")
        self.logger.info("  Num examples = %d", len(self.train_examples))
        self.logger.info("  Batch size = %d", self.opt.batch_size)
        self.logger.info("  Num steps = %d", self.num_train_optimization_steps)
        sum_loss = 0
        sum_apc_test_acc = 0
        sum_apc_test_f1 = 0
        sum_ate_test_f1 = 0
        # max_apc_test_acc = 0
        # max_apc_test_f1 = 0
        # max_ate_test_f1 = 0
        self.opt.max_test_metrics = {'max_apc_test_acc': 0, 'max_apc_test_f1': 0, 'max_ate_test_f1': 0}
        self.opt.metrics_of_this_checkpoint = {'apc_acc': 0, 'apc_f1': 0, 'ate_f1': 0}
        global_step = 0
        save_path = ''
        for epoch in range(int(self.opt.num_epoch)):
            nb_tr_examples, nb_tr_steps = 0, 0
            iterator = tqdm.tqdm(self.train_dataloader)
            for step, batch in enumerate(iterator):
                self.model.train()
                batch = tuple(t.to(self.opt.device) for t in batch)
                input_ids_spc, segment_ids, input_mask, label_ids, polarity, \
                valid_ids, l_mask, lcf_cdm_vec, lcf_cdw_vec = batch
                loss_ate, loss_apc = self.model(input_ids_spc,
                                                token_type_ids=segment_ids,
                                                attention_mask=input_mask,
                                                labels=label_ids,
                                                polarity=polarity,
                                                valid_ids=valid_ids,
                                                attention_mask_label=l_mask,
                                                lcf_cdm_vec=lcf_cdm_vec,
                                                lcf_cdw_vec=lcf_cdw_vec
                                                )
                loss = loss_ate + loss_apc
                sum_loss += loss.item()
                loss.backward()
                nb_tr_examples += input_ids_spc.size(0)
                nb_tr_steps += 1
                self.optimizer.step()
                self.optimizer.zero_grad()
                global_step += 1
                global_step += 1
                if 'test' in self.opt.dataset_file and global_step % self.opt.log_step == 0:
                    if epoch >= self.opt.evaluate_begin:
                        apc_result, ate_result = self.evaluate(
                            eval_ATE=not (self.opt.model_name == 'lcf_atepc' and self.opt.use_bert_spc))
                        sum_apc_test_acc += apc_result['apc_test_acc']
                        sum_apc_test_f1 += apc_result['apc_test_f1']
                        sum_ate_test_f1 += ate_result
                        self.opt.metrics_of_this_checkpoint['apc_acc'] = sum_apc_test_acc
                        self.opt.metrics_of_this_checkpoint['apc_f1'] = sum_apc_test_f1
                        self.opt.metrics_of_this_checkpoint['ate_f1'] = sum_ate_test_f1
                        # if save_path:
                        #     try:
                        #         shutil.rmtree(save_path)
                        #         # self.logger.info('Remove sub-self.optimal trained model:', save_path)
                        #     except:
                        #         self.logger.info('Can not remove sub-self.optimal trained model:', save_path)
                        if self.opt.model_path_to_save:
                            save_path = '{0}/{1}_{2}_apcacc_{3}_apcf1_{4}_atef1_{5}/'.format(
                                self.opt.model_path_to_save,
                                self.opt.model_name,
                                self.opt.lcf,
                                round(apc_result['apc_test_acc'], 2),
                                round(apc_result['apc_test_f1'], 2),
                                round(ate_result, 2)
                            )
                            if apc_result['apc_test_acc'] > self.opt.max_test_metrics['max_apc_test_acc'] or \
                                    apc_result['apc_test_f1'] > self.opt.max_test_metrics['max_apc_test_f1'] or \
                                    ate_result > self.opt.max_test_metrics['max_ate_test_f1']:
                                self._save_model(self.opt, self.model, save_path, mode=0)

                        if apc_result['apc_test_acc'] > self.opt.max_test_metrics['max_apc_test_acc']:
                            self.opt.max_test_metrics['max_apc_test_acc'] = apc_result['apc_test_acc']
                        if apc_result['apc_test_f1'] > self.opt.max_test_metrics['max_apc_test_f1']:
                            self.opt.max_test_metrics['max_apc_test_f1'] = apc_result['apc_test_f1']
                        if ate_result > self.opt.max_test_metrics['max_ate_test_f1']:
                            self.opt.max_test_metrics['max_ate_test_f1'] = ate_result

                        current_apc_test_acc = apc_result['apc_test_acc']
                        current_apc_test_f1 = apc_result['apc_test_f1']
                        current_ate_test_f1 = round(ate_result, 2)

                        postfix = 'Epoch:{} | '.format(epoch)

                        postfix += 'loss_apc:{:.4f} | loss_ate:{:.4f} |'.format(loss_apc.item(), loss_ate.item())

                        postfix += ' APC_ACC: {}(max:{}) | APC_F1: {}(max:{}) | '.format(current_apc_test_acc,
                                                                                         self.opt.max_test_metrics[
                                                                                             'max_apc_test_acc'],
                                                                                         current_apc_test_f1,
                                                                                         self.opt.max_test_metrics[
                                                                                             'max_apc_test_f1']
                                                                                         )
                        if self.opt.model_name == 'lcf_atepc' and self.opt.use_bert_spc:
                            postfix += 'ATE_F1: N.A. for LCF-ATEPC under use_bert_spc=True)'
                        else:
                            postfix += 'ATE_F1: {}(max:{})'.format(current_ate_test_f1, self.opt.max_test_metrics[
                                'max_ate_test_f1'])
                    else:
                        postfix = 'Epoch:{} | No evaluation until epoch:{}'.format(epoch, self.opt.evaluate_begin)

                    iterator.postfix = postfix
                    iterator.refresh()

        self.logger.info('-------------------------------------Training Summary-------------------------------------')
        self.logger.info(
            '  Max APC Acc: {:.5f} Max APC F1: {:.5f} Max ATE F1: {:.5f} Accumulated Loss: {}'.format(
                self.opt.max_test_metrics['max_apc_test_acc'],
                self.opt.max_test_metrics['max_apc_test_f1'],
                self.opt.max_test_metrics['max_ate_test_f1'],
                sum_loss)
        )
        self.logger.info('-------------------------------------Training Summary-------------------------------------')
        # return the model paths of multiple training_tutorials
        # in case of loading the best model after training_tutorials
        if save_path:
            return save_path
        else:
            # direct return model if do not evaluate
            if self.opt.model_path_to_save:
                save_path = '{0}/{1}_{2}/'.format(self.opt.model_path_to_save,
                                                  self.opt.model_name,
                                                  self.opt.lcf,
                                                  )
                self._save_model(self.opt, self.model, save_path, mode=0)
            return self.model, self.opt, self.tokenizer, sum_apc_test_acc, sum_apc_test_f1, sum_ate_test_f1

    def evaluate(self, eval_ATE=True, eval_APC=True):
        apc_result = {'apc_test_acc': 0, 'apc_test_f1': 0}
        ate_result = 0
        y_true = []
        y_pred = []
        n_test_correct, n_test_total = 0, 0
        test_apc_logits_all, test_polarities_all = None, None
        self.model.eval()
        label_map = {i: label for i, label in enumerate(self.label_list, 1)}

        for i, batch in enumerate(self.eval_dataloader):
            input_ids_spc, segment_ids, input_mask, label_ids, polarity, \
            valid_ids, l_mask, lcf_cdm_vec, lcf_cdw_vec = batch

            input_ids_spc = input_ids_spc.to(self.opt.device)
            input_mask = input_mask.to(self.opt.device)
            segment_ids = segment_ids.to(self.opt.device)
            valid_ids = valid_ids.to(self.opt.device)
            label_ids = label_ids.to(self.opt.device)
            polarity = polarity.to(self.opt.device)
            l_mask = l_mask.to(self.opt.device)
            lcf_cdm_vec = lcf_cdm_vec.to(self.opt.device)
            lcf_cdw_vec = lcf_cdw_vec.to(self.opt.device)

            with torch.no_grad():
                ate_logits, apc_logits = self.model(input_ids_spc,
                                                    token_type_ids=segment_ids,
                                                    attention_mask=input_mask,
                                                    labels=None,
                                                    polarity=polarity,
                                                    valid_ids=valid_ids,
                                                    attention_mask_label=l_mask,
                                                    lcf_cdm_vec=lcf_cdm_vec,
                                                    lcf_cdw_vec=lcf_cdw_vec
                                                    )
            if eval_APC:
                n_test_correct += (torch.argmax(apc_logits, -1) == polarity).sum().item()
                n_test_total += len(polarity)

                if test_polarities_all is None:
                    test_polarities_all = polarity
                    test_apc_logits_all = apc_logits
                else:
                    test_polarities_all = torch.cat((test_polarities_all, polarity), dim=0)
                    test_apc_logits_all = torch.cat((test_apc_logits_all, apc_logits), dim=0)

            if eval_ATE:
                if not self.opt.use_bert_spc:
                    label_ids = self.model.get_batch_token_labels_bert_base_indices(label_ids)
                ate_logits = torch.argmax(F.log_softmax(ate_logits, dim=2), dim=2)
                ate_logits = ate_logits.detach().cpu().numpy()
                label_ids = label_ids.to('cpu').numpy()
                input_mask = input_mask.to('cpu').numpy()
                for i, label in enumerate(label_ids):
                    temp_1 = []
                    temp_2 = []
                    for j, m in enumerate(label):
                        if j == 0:
                            continue
                        elif label_ids[i][j] == len(self.label_list):
                            y_true.append(temp_1)
                            y_pred.append(temp_2)
                            break
                        else:
                            temp_1.append(label_map.get(label_ids[i][j], 'O'))
                            temp_2.append(label_map.get(ate_logits[i][j], 'O'))
        if eval_APC:
            test_acc = n_test_correct / n_test_total

            test_f1 = f1_score(torch.argmax(test_apc_logits_all, -1).cpu(), test_polarities_all.cpu(),
                               labels=list(range(self.opt.polarities_dim)), average='macro')

            test_acc = round(test_acc * 100, 2)
            test_f1 = round(test_f1 * 100, 2)
            apc_result = {'apc_test_acc': test_acc, 'apc_test_f1': test_f1}

        if eval_ATE:
            report = classification_report(y_true, y_pred, digits=4)
            tmps = report.split()
            ate_result = round(float(tmps[7]) * 100, 2)
        return apc_result, ate_result

    def _save_model(self, args_to_save, model_to_save, save_path, mode=0):
        # Save a trained model, configuration and tokenizer
        model_to_save = model_to_save.module if hasattr(model_to_save,
                                                        'tasks') else model_to_save  # Only save the model it-self

        if mode == 0:
            if not os.path.exists(save_path):
                os.makedirs(save_path)
            # torch.save(model_to_save.cpu().state_dict(),
            #            save_path + args_to_save.model_name + '.state_dict')  # save the state dict
            torch.save(model_to_save.cpu(), save_path + args_to_save.model_name + '.model')  # save the whole model
            pickle.dump(args_to_save, open(save_path + args_to_save.model_name + '.config', 'wb'))
            pickle.dump(self.tokenizer, open(save_path + args_to_save.model_name + '.tokenizer', 'wb'))
        else:
            # save the fine-tuned bert model
            model_output_dir = save_path
            if not os.path.exists(model_output_dir):
                os.makedirs(model_output_dir)
            output_model_file = os.path.join(model_output_dir, 'pytorch_model.bin')
            output_config_file = os.path.join(model_output_dir, 'bert_config.json')

            torch.save(model_to_save.state_dict(), output_model_file)
            model_to_save.config.to_json_file(output_config_file)
            self.tokenizer.save_vocabulary(model_output_dir)

        # self.logger.info('trained model saved in: {}'.format(save_path))
        model_to_save.to(args_to_save.device)


def train4atepc(opt):
    # in case of handling ConnectionError exception
    trainer = None
    while not trainer:
        try:
            trainer = Instructor(opt)
        except ValueError as e:
            print('Seems to be ConnectionError, retry in {} seconds...'.format(60))
            time.sleep(60)
    return trainer.train()
