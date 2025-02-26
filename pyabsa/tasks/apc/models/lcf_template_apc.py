# -*- coding: utf-8 -*-
# file: lcf_template_apc.py
# time: 2021/6/22
# author: yangheng <yangheng@m.scnu.edu.cn>
# github: https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.

import torch
import torch.nn as nn
from transformers.models.bert.modeling_bert import BertPooler
from pyabsa.network.sa_encoder import Encoder


class LCF_TEMPLATE_BERT(nn.Module):
    def __init__(self, bert, opt):
        super(LCF_TEMPLATE_BERT, self).__init__()
        self.bert4global = bert
        self.bert4local = self.bert4global
        self.opt = opt
        self.dropout = nn.Dropout(opt.dropout)

    def forward(self, inputs):

        raise NotImplementedError('This is a template ATEPC model based on LCF, '
                          'please implement your model use this template.')
