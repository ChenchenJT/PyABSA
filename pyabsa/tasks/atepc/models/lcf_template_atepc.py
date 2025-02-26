# -*- coding: utf-8 -*-
# file: lcf_template_atepc.py
# time: 2021/6/22
# author: yangheng <yangheng@m.scnu.edu.cn>
# github: https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.


from torch.nn import CrossEntropyLoss
import torch
import torch.nn as nn
import copy
import numpy as np

from transformers.models.bert.modeling_bert import BertForTokenClassification, BertPooler

from pyabsa.tasks.atepc.dataset_utils.data_utils_for_training import SENTIMENT_PADDING
from pyabsa.network.sa_encoder import Encoder


class LCF_TEMPLATE_ATEPC(BertForTokenClassification):

    def __init__(self, bert_base_model, opt):
        super(LCF_TEMPLATE_ATEPC, self).__init__(config=bert_base_model.config)
        config = bert_base_model.config
        self.bert4global = bert_base_model
        self.opt = opt
        self.bert4local = self.bert4global
        self.dropout = nn.Dropout(self.opt.dropout)


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
        raise NotImplementedError('This is a template ATEPC model based on LCF, '
                                  'please implement your model use this template.')
