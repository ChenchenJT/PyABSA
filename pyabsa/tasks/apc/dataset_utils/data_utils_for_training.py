# -*- coding: utf-8 -*-
# file: data_utils_for_training.py
# time: 2021/5/31 0031
# author: yangheng <yangheng@m.scnu.edu.cn>
# github: https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.

import tqdm
from torch.utils.data import Dataset
from .apc_utils import build_sentiment_window
from .apc_utils import build_spc_mask_vec
from .apc_utils import load_datasets, prepare_input_for_apc

from pyabsa.tasks.apc.models import BERT_BASE, BERT_SPC

from pyabsa.tasks.apc.models import LCF_BERT, FAST_LCF_BERT, LCF_BERT_LARGE

from pyabsa.tasks.apc.models import LCFS_BERT, FAST_LCFS_BERT, LCFS_BERT_LARGE

from pyabsa.tasks.apc.models import SLIDE_LCF_BERT, SLIDE_LCFS_BERT

from pyabsa.tasks.apc.models import LCA_BERT

from pyabsa.tasks.apc.models import LCF_TEMPLATE_BERT


class ABSADataset(Dataset):
    input_colses = {
        BERT_BASE: ['text_raw_bert_indices'],
        BERT_SPC: ['text_bert_indices'],
        LCA_BERT: ['text_bert_indices', 'text_raw_bert_indices', 'lca_ids', 'lcf_vec'],
        LCF_BERT: ['text_bert_indices', 'text_raw_bert_indices', 'lcf_vec'],
        FAST_LCF_BERT: ['text_bert_indices', 'text_raw_bert_indices', 'lcf_vec'],
        LCF_BERT_LARGE: ['text_bert_indices', 'text_raw_bert_indices', 'lcf_vec'],
        LCFS_BERT: ['text_bert_indices', 'text_raw_bert_indices', 'lcf_vec'],
        FAST_LCFS_BERT: ['text_bert_indices', 'text_raw_bert_indices', 'lcf_vec'],
        LCFS_BERT_LARGE: ['text_bert_indices', 'text_raw_bert_indices', 'lcf_vec'],
        SLIDE_LCFS_BERT: ['text_bert_indices', 'spc_mask_vec', 'lcf_vec', 'left_lcf_vec', 'right_lcf_vec'],
        SLIDE_LCF_BERT: ['text_bert_indices', 'spc_mask_vec', 'lcf_vec', 'left_lcf_vec', 'right_lcf_vec'],
        LCF_TEMPLATE_BERT: ['text_bert_indices', 'text_raw_bert_indices', 'lcf_vec'],
    }

    def __init__(self, fname, tokenizer, opt):

        ABSADataset.opt = opt

        lines = load_datasets(fname)

        all_data = []

        # record polarities type to update polarities_dim
        polarities_set = set()

        for i in tqdm.tqdm(range(0, len(lines), 3), postfix='building word indices...'):
            text_left, _, text_right = [s.strip() for s in lines[i].partition("$T$")]
            aspect = lines[i + 1].lower().strip()
            polarity = lines[i + 2].strip()
            polarity = int(polarity)
            polarities_set.add(polarity)

            prepared_inputs = prepare_input_for_apc(opt, tokenizer, text_left, text_right, aspect)

            text_raw = prepared_inputs['text_raw']
            aspect = prepared_inputs['aspect']
            text_bert_indices = prepared_inputs['text_bert_indices']
            text_raw_bert_indices = prepared_inputs['text_raw_bert_indices']
            aspect_bert_indices = prepared_inputs['aspect_bert_indices']
            lca_ids = prepared_inputs['lca_ids']
            lcf_vec = prepared_inputs['lcf_cdm_vec'] if opt.lcf == 'cdm' else prepared_inputs['lcf_cdw_vec']
            data = {
                'text_raw': text_raw,

                'aspect': aspect,

                'lca_ids': lca_ids if 'lca_ids' in ABSADataset.input_colses[opt.model] else 0,

                'lcf_vec': lcf_vec if 'lcf_vec' in ABSADataset.input_colses[opt.model] else 0,

                'spc_mask_vec': build_spc_mask_vec(opt, text_raw_bert_indices)
                if 'spc_mask_vec' in ABSADataset.input_colses[opt.model] else 0,

                'text_bert_indices': text_bert_indices
                if 'text_bert_indices' in ABSADataset.input_colses[opt.model] else 0,

                'aspect_bert_indices': aspect_bert_indices
                if 'aspect_bert_indices' in ABSADataset.input_colses[opt.model] else 0,

                'text_raw_bert_indices': text_raw_bert_indices
                if 'text_raw_bert_indices' in ABSADataset.input_colses[opt.model] else 0,

                'polarity': polarity,
            }

            all_data.append(data)

        if 'slide' in opt.model_name:
            all_data = build_sentiment_window(all_data, tokenizer, opt.similarity_threshold)

        # update polarities_dim, init model behind this function!
        p_min, p_max = min(polarities_set), max(polarities_set)
        if p_min < 0:
            raise RuntimeError('Invalid sentiment label detected, only please label the sentiment between {0, N-1} '
                               '(assume there are N types of sentiment polarities.)')
        assert sorted(list(polarities_set)) == sorted(list(range(p_max - p_min + 1)))
        opt.polarities_dim = len(polarities_set)

        self.data = all_data

    def __getitem__(self, index):
        return self.data[index]

    def __len__(self):
        return len(self.data)
