# -*- coding: utf-8 -*-
# @FileName: lcf_atepc_large.py
# @Time    : 2021/6/20 10:07
# @Author  : yangheng@m.scnu.edu.cn
# @github  : https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.

from torch.nn import CrossEntropyLoss
import torch
import torch.nn as nn
import copy
import numpy as np

from transformers.models.bert.modeling_bert import BertForTokenClassification, BertPooler

from pyabsa.tasks.atepc.dataset_utils.data_utils_for_training import SENTIMENT_PADDING
from pyabsa.network.sa_encoder import Encoder


class LCF_ATEPC_LARGE(BertForTokenClassification):

    def __init__(self, bert_base_model, opt):
        super(LCF_ATEPC_LARGE, self).__init__(config=bert_base_model.config)
        config = bert_base_model.config
        self.bert4global = bert_base_model
        self.opt = opt
        self.bert4local = copy.deepcopy(self.bert4global)

        self.dropout = nn.Dropout(self.opt.dropout)
        self.SA1 = Encoder(config, opt)
        self.SA2 = Encoder(config, opt)
        self.linear_double = nn.Linear(opt.hidden_dim * 2, opt.hidden_dim)
        self.linear_triple = nn.Linear(opt.hidden_dim * 3, opt.hidden_dim)

        self.pooler = BertPooler(config)
        self.dense = torch.nn.Linear(opt.hidden_dim, opt.polarities_dim)

    def get_batch_token_labels_bert_base_indices(self, labels):
        if labels is None:
            return
        # convert tags of BERT-SPC input to BERT-BASE format
        labels = labels.detach().cpu().numpy()
        for text_i in range(len(labels)):
            sep_index = np.argmax((labels[text_i] == 5))
            labels[text_i][sep_index + 1:] = 0
        return torch.tensor(labels).to(self.opt.device)

    def get_ids_for_local_context_extractor(self, text_indices):
        # convert BERT-SPC input to BERT-BASE format
        text_ids = text_indices.detach().cpu().numpy()
        for text_i in range(len(text_ids)):
            sep_index = np.argmax((text_ids[text_i] == 102))
            text_ids[text_i][sep_index + 1:] = 0
        return torch.tensor(text_ids).to(self.opt.device)

    def forward(self, input_ids_spc,
                token_type_ids=None,
                attention_mask=None,
                labels=None,
                polarity=None,
                valid_ids=None,
                attention_mask_label=None,
                lcf_cdm_vec=None,
                lcf_cdw_vec=None
                ):
        if not self.opt.use_bert_spc:
            input_ids = self.get_ids_for_local_context_extractor(input_ids_spc)
            labels = self.get_batch_token_labels_bert_base_indices(labels)
            global_context_out = self.bert4global(input_ids, token_type_ids, attention_mask)['last_hidden_state']
        else:
            global_context_out = self.bert4global(input_ids_spc, token_type_ids, attention_mask)['last_hidden_state']

        batch_size, max_len, feat_dim = global_context_out.shape
        global_valid_output = torch.zeros(batch_size, max_len, feat_dim, dtype=torch.float32).to(self.opt.device)
        for i in range(batch_size):
            jj = -1
            for j in range(max_len):
                if valid_ids[i][j].item() == 1:
                    jj += 1
                    global_valid_output[i][jj] = global_context_out[i][j]
        global_context_out = self.dropout(global_valid_output)
        ate_logits = self.classifier(global_context_out)

        if lcf_cdm_vec is not None or lcf_cdw_vec is not None:
            local_context_ids = self.get_ids_for_local_context_extractor(input_ids_spc)
            local_context_out = self.bert4local(local_context_ids)['last_hidden_state']
            batch_size, max_len, feat_dim = local_context_out.shape
            local_valid_output = torch.zeros(batch_size, max_len, feat_dim, dtype=torch.float32).to(self.opt.device)
            for i in range(batch_size):
                jj = -1
                for j in range(max_len):
                    if valid_ids[i][j].item() == 1:
                        jj += 1
                        local_valid_output[i][jj] = local_context_out[i][j]
            local_context_out = self.dropout(local_valid_output)

            if 'cdm' in self.opt.lcf:
                cdm_context_out = torch.mul(local_context_out, lcf_cdm_vec)
                cdm_context_out = self.SA1(cdm_context_out)
                cat_out = torch.cat((global_context_out, cdm_context_out), dim=-1)
                cat_out = self.linear_double(cat_out)
            elif 'cdw' in self.opt.lcf:
                cdw_context_out = torch.mul(local_context_out, lcf_cdw_vec)
                cdw_context_out = self.SA1(cdw_context_out)
                cat_out = torch.cat((global_context_out, cdw_context_out), dim=-1)
                cat_out = self.linear_double(cat_out)
            elif 'fusion' in self.opt.lcf:
                cdm_context_out = torch.mul(local_context_out, lcf_cdm_vec)
                cdw_context_out = torch.mul(local_context_out, lcf_cdw_vec)
                cat_out = torch.cat((global_context_out, cdw_context_out, cdm_context_out), dim=-1)
                cat_out = self.linear_triple(cat_out)
            sa_out = self.SA2(cat_out)
            pooled_out = self.pooler(sa_out)
            pooled_out = self.dropout(pooled_out)
            apc_logits = self.dense(pooled_out)
        else:
            apc_logits = None

        if labels is not None:
            criterion_ate = CrossEntropyLoss(ignore_index=0)
            criterion_apc = CrossEntropyLoss(ignore_index=SENTIMENT_PADDING)
            loss_ate = criterion_ate(ate_logits.view(-1, self.num_labels), labels.view(-1))
            loss_apc = criterion_apc(apc_logits, polarity)
            return loss_ate, loss_apc
        else:
            return ate_logits, apc_logits
