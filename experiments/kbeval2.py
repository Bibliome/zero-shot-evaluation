#!/bin/env python


import json
import re
from datetime import datetime
from typing import Union, Callable

from evaluation.pairing import MunkresPairing
from evaluation.scoring import BaseScores, IEScores


def log(msg):
    now = datetime.now()
    sys.stderr.write(now.strftime('[%Y-%m-%d %H:%M:%S] ') + msg + '\n')


JUNK = re.compile('[\W-]+')
def normalize_string(s: str) -> str:
    return ' '.join(c for c in JUNK.split(s) if c != '').lower()


class PredictionJsonReader:
    CODEBLOCK = re.compile('```json(.*)```', re.DOTALL)

    @staticmethod
    def remove_codeblock(content: str) -> str:
        m = PredictionJsonReader.CODEBLOCK.search(content)
        if m is None:
            return content
        return m.group(1)


    LAST_COMMA = re.compile(r',(?=\s*[}\]])')

    @staticmethod
    def remove_last_comma(content: str) -> str:
        return PredictionJsonReader.LAST_COMMA.sub('', content)

    @staticmethod
    def squash_list(j: Union[list, dict]) -> dict:
        if isinstance(j, list):
            entities=[]
            relationships=[]
            for elt in j:
                entities.extend(elt.get('entities', []))
                relationships.extend(elt.get('relationships', []))
            return dict(entities=entities, relationships=relationships)
        return j

    @staticmethod
    def locate_arguments(rel: dict):
        if 'source' in rel and 'target' in rel:
            pass
        if 'arguments' in rel:
            rel.update(rel['arguments'])

    TYPE_MAP = {
        'cause': 'causes',
        'affect': 'affects',
        'have been found on': 'has been found on',
        'transmit': 'transmits'
    }

    @staticmethod
    def normalize_type(rel: dict):
        type_ = rel['type']
        type_ = normalize_string(type_)
        type_ = PredictionJsonReader.TYPE_MAP.get(type_, type_)
        rel['type'] = type_

    @staticmethod
    def normalize_args(rel):
        rel['source'] = normalize_string(rel['source'])
        rel['target'] = normalize_string(rel['target'])

    @staticmethod
    def load(filename: str) -> list:
        log(f'reading {filename}')
        with open(filename) as f:
            js = f.read().strip()
        js = PredictionJsonReader.remove_codeblock(js)
        js = PredictionJsonReader.remove_last_comma(js)
        j = json.loads(js)
        j = PredictionJsonReader.squash_list(j)
        relationships = j.get('relationships', [])
        for rel in relationships:
            PredictionJsonReader.locate_arguments(rel)
            PredictionJsonReader.normalize_type(rel)
            PredictionJsonReader.normalize_args(rel)
        return relationships


def strict_string_similarity(ref: str, pred: str) -> float:
    return float(ref == pred)


def relation_similarity(type_similarity: Callable[[str, str], float] = strict_string_similarity, arg_similarity: Callable[[str, str], float] = strict_string_similarity) -> Callable[[dict, dict], float]:
    def result(ref, pred):
        type_score = type_similarity(ref['type'], pred['type'])
        source_score = max(arg_similarity(f, pred['source']) for f in ref['source'])
        target_score = max(arg_similarity(f, pred['target']) for f in ref['target'])
        return type_score * source_score * target_score
    return result


if __name__ == '__main__':
    import sys
    print(PredictionJsonReader.load(sys.argv[1]))
