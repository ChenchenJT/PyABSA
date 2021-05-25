# -*- coding: utf-8 -*-
# file: pyabsa_utils.py
# time: 2021/5/20 0020
# author: yangheng <yangheng@m.scnu.edu.cn>
# github: https://github.com/yangheng95
# Copyright (C) 2021. All Rights Reserved.

import os
import torch


def get_auto_device():
    choice = -1
    if torch.cuda.is_available():
        from .Pytorch_GPUManager import GPUManager
        choice = GPUManager().auto_choice()
    return choice


def find_target_file(dir_path, file_type, exclude_key='', find_all=False):
    if not dir_path:
        return ''
    elif os.path.isfile(dir_path) and file_type in dir_path:
        return [dir_path] if find_all else dir_path
    elif os.path.isfile(dir_path) and file_type not in dir_path:
        return ''
    elif not find_all:
        path = os.path.join(dir_path,
                            [p for p in os.listdir(dir_path)
                             if file_type in p.lower()
                             and not (exclude_key and exclude_key in p.lower())][0])
    else:
        path = [os.path.join(dir_path, p)
                for p in os.listdir(dir_path)
                if file_type in p.lower()
                and not (exclude_key and exclude_key in p.lower())]

    return path
