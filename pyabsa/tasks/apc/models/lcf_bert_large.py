# -*- coding: utf-8 -*-
# @FileName: lcf_bert_large.py
# @Time    : 2021/6/20 9:29
# @Author  : yangheng@m.scnu.edu.cn
# @github  : https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.

import copy

import torch
import torch.nn as nn
from transformers.models.bert.modeling_bert import BertPooler
from pyabsa.network.sa_encoder import Encoder


class LCF_BERT_LARGE(nn.Module):
    def __init__(self, bert, opt):
        super(LCF_BERT_LARGE, self).__init__()
        self.bert4global = bert
        self.bert4local = copy.deepcopy(bert)
        self.opt = opt
        self.dropout = nn.Dropout(opt.dropout)
        self.bert_SA = Encoder(bert.config, opt)
        self.linear2 = nn.Linear(opt.embed_dim * 2, opt.embed_dim)
        self.bert_SA_ = Encoder(bert.config, opt)
        self.bert_pooler = BertPooler(bert.config)
        self.dense = nn.Linear(opt.embed_dim, opt.polarities_dim)

    def forward(self, inputs):
        if self.opt.use_bert_spc:
            text_bert_indices = inputs[0]
        else:
            text_bert_indices = inputs[1]
        text_local_indices = inputs[1]
        lcf_matrix = inputs[2]
        global_context_features = self.bert4global(text_bert_indices)['last_hidden_state']
        local_context_features = self.bert4local(text_local_indices)['last_hidden_state']

        # LCF layer
        lcf_features = torch.mul(local_context_features, lcf_matrix)
        lcf_features = self.bert_SA(lcf_features)

        cat_features = torch.cat((lcf_features, global_context_features), dim=-1)
        cat_features = self.linear2(cat_features)
        cat_features = self.dropout(cat_features)
        cat_features = self.bert_SA_(cat_features)
        pooled_out = self.bert_pooler(cat_features)
        dense_out = self.dense(pooled_out)
        return dense_out
