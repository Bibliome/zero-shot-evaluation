#!/bin/env python


import json
import re
import sys
from datetime import datetime
from evaluation.pairing import MunkresPairing
from evaluation.scoring import BaseScores, IEScores


def log(msg):
    now = datetime.now()
    sys.stderr.write(now.strftime('[%Y-%m-%d %H:%M:%S] ') + msg + '\n')


NORM_TYPES = ('NCBI_Taxonomy', 'GeoNames', 'OntoBiotope', 'name')


CODEBLOCK = re.compile('```json(.*)```', re.DOTALL)
def remove_codeblock(content):
    m = CODEBLOCK.search(content)
    if m is None:
        return content
    return m.group(1)
   

LAST_COMMA = re.compile(r',(?=\s*[}\]])')
def remove_last_comma(content):
    return LAST_COMMA.sub('', content)


def squash_list(j):
    if isinstance(j, list):
        entities=[]
        relationships=[]
        for elt in j:
            entities.extend(elt.get('entities', []))
            relationships.extend(elt.get('relationships', []))
        return dict(entities=entities, relationships=relationships)
    return j


class Entity:
    def __init__(self, **args):
        self.id_ = args.get('id')
        self.type_ = args['type']
        self.name = args['name']
        for nt in NORM_TYPES:
            if nt in args:
                setattr(self, nt, args[nt])
                self.normalization_type = nt
                self.normalization_value = args[nt]
                break
        self.key = self.type_, self.normalization_type, self.normalization_value

    def __str__(self):
        return f'Entity({self.type_}, "{self.name}", {self.normalization_type}: {self.normalization_value})'

    def __repr__(self):
        return str(self)


class MergedEntity:
    QUOTES = set('"\'\u2018\u2019\u201c\u201d\u0060\u00b4')

    def __init__(self, ent):
        self.type_ = ent.type_
        self.ids = {ent.id_}
        self.names = {ent.name}
        self.normalization_type = ent.normalization_type
        self.normalization_value = ent.normalization_value
        setattr(self, ent.normalization_type, ent.normalization_value)
        self.key = ent.key

    def add(self, ent):
        self.ids.add(ent.id_)
        self.names.add(ent.name)

    def match_name(self, pred_name):
        if pred_name[0] in MergedEntity.QUOTES and pred_name[-1] in MergedEntity.QUOTES:
            pred_name = pred_name[1:-1]
            # log(pred_name)
        pred_name = pred_name.lower()
        for name in self.names:
            if name.lower() == pred_name:
                return True
        return False

    @staticmethod
    def _jaccard_seq(seq1, seq2):
        # log(f'### seq1 = {seq1} _ seq2 = {seq2}')
        n1 = len(seq1)
        n2 = len(seq2)
        best = 0
        for shift in range(1 - n1, n2):
            start1 = max(0, -shift)
            start2 = max(0, shift)
            # log(f'shift = {shift} _ start1 = {start1} _ start2 = {start2}')
            sub1 = seq1[start1:]
            sub2 = seq2[start2:]
            # log(f'sub1 = {sub1} _ sub2 = {sub2}')
            m = min(len(sub1), len(sub2))
            if m > best and sub1[0:m] == sub2[0:m]:
                best = m
        # log(f'best = {best}')
        union = n1 + n2 - best
        return float(best) / union

    def jaccard_name(self, pred_name):
        if pred_name[0] in MergedEntity.QUOTES and pred_name[-1] in MergedEntity.QUOTES:
            pred_name = pred_name[1:-1]
            # log(pred_name)
        pred_tokens = pred_name.lower().split()
        return max(MergedEntity._jaccard_seq(name.lower().split(), pred_tokens) for name in self.names)

    def __str__(self):
        return f'MergedEntity({self.type_}, {self.ids}, {self.names}, {self.normalization_type}: {self.normalization_value})'

    def __repr__(self):
        return str(self)


class Relation:
    def __init__(self, **args):
        self.type_ = args['type']
        if 'arguments' in args:
            self.source = args['arguments']['source']
            self.target = args['arguments']['target']
        else:
            self.source = args['source']
            self.target = args['target']

    def key(self, ent_id_map):
        source_type, source_nt, source_nv = ent_id_map[self.source].key
        target_type, target_nt, target_nv = ent_id_map[self.target].key
        return self.type_, source_type, source_nt, source_nv, target_type, target_nt, target_nv

    def __str__(self):
        return f'Relation({self.type_}, {self.source}, {self.target})'

    def __repr__(self):
        return str(self)


class MergedRelation:
    JUNK_CHARS_IN_TYPE = re.compile(r'[\s_]+')
    TYPEMAP = {
        'Cause': 'Causes',
        'Affect': 'Affects',
        'Have been found on': 'Has been found on',
        'Transmit': 'Transmits'
    }
    
    def __init__(self, ent_id_map, rel):
        self.type_ = rel.type_
        self.source = ent_id_map[rel.source]
        self.target = ent_id_map[rel.target]

    @staticmethod
    def _normalize_type(type_):
        nt = MergedRelation.JUNK_CHARS_IN_TYPE.sub('', MergedRelation.TYPEMAP.get(type_, type_)).lower()
        return nt
    
    def match_type(self, pred_type):
        return MergedRelation._normalize_type(self.type_) == MergedRelation._normalize_type(pred_type)

    def __str__(self):
        return f'MergedRelation({self.type_}, {self.source}, {self.target})'

    def __repr__(self):
        return str(self)


class Dataset:
    def __init__(self, entities, relations, equivalences):
        self.entities = entities
        self.relations = relations
        self.equivalences = equivalences

    @staticmethod
    def from_json_file(filename):
        log(f'reading {filename}')
        try:
            with open(filename) as f:
                jc = f.read().strip()
        except FileNotFoundError:
            log('ERROR: file not found')
            exit(1)
        jc = remove_codeblock(jc)
        jc = remove_last_comma(jc)
        try:
            j = json.loads(jc)
        except json.decoder.JSONDecodeError:
            log('ERROR: malformed JSON')
            return Dataset([], [], [])
        j = squash_list(j)

        if not j.get('relationships'):
            j['relationships'] = []

        entities = list(Entity(**ent) for ent in j['entities'])
        relations = list(Relation(**rel) for rel in j['relationships'])
        if 'equivalences' in j:
            equivalences = list(set(eq) for eq in j['equivalences'])
        else:
            equivalences = []
        if len(relations) == 0:
            log('WARNING: empty relations')
        return Dataset(entities, relations, equivalences)

    def merge_ref(self):
        log('merging reference relations')
        entities = list(self._merge_ref_entities())
        relations = list(self._merge_ref_relations(entities))
        return MergedRefDataset(entities, relations)

    def _merge_ref_entities(self):
        ent_map = dict()
        eqid_map = dict()
        for ent in self.entities:
            if ent.key in ent_map:
                ent_map[ent.key].add(ent)
            elif ent.id_ in eqid_map:
                eqid_map[ent.id_].add(ent)
            else:
                me = MergedEntity(ent)
                for eq in self.equivalences:
                    if ent.id_ in eq:
                        for id_ in eq:
                            eqid_map[id_] = me
                ent_map[ent.key] = me
                yield me
    
    def _merge_ref_relations(self, entities):
        ent_id_map = dict()
        for me in entities:
            for id_ in me.ids:
                ent_id_map[id_] = me
        rel_map = set()
        for rel in self.relations:
            key = rel.key(ent_id_map)
            if key not in rel_map:
                rel_map.add(key)
                yield MergedRelation(ent_id_map, rel)


class MergedRefDataset(Dataset):
    def __init__(self, entities, relations):
        Dataset.__init__(self, entities, relations, ())

    def _map_name_to_entity(self, pred_ent):
        for ref_ent in self.entities:
            if ref_ent.match_name(pred_ent):
                return ref_ent
        return None

    def map_entities(self, pred):
        return dict((pred_ent, self._map_name_to_entity(pred_ent.name)) for pred_ent in pred.entities)

    @staticmethod
    def from_json_file(filename):
        return Dataset.from_json_file(filename).merge_ref()


def standard_type_similarity(ref, type_):
    return float(ref.match_type(type_))


def relaxed_type_similarity(ref, type_):
    if ref.match_type(type_):
        return 1.0
    return 0.9


def standard_arg_similarity(ref, name):
    return float(ref.match_name(name))


def relaxed_arg_similarity(ref, name):
    return ref.jaccard_name(name)


def relation_similarity(type_sim, arg_sim):
    def sim(ref, pred):
        return type_sim(ref, pred.type_) * arg_sim(ref.source, pred.source) * arg_sim(ref.target, pred.target)
    return sim


def log_scores(name, scores):
    log(f'{name} scores: ')
    for k, v in scores.items():
        log(f'  {k}: {v}')


def pred_redundant(ref, pred):
    sim = relation_similarity(standard_type_similarity, standard_arg_similarity)
    for r in ref:
        found = False
        for p in pred:
            if sim(r, p) == 1.0:
                if found:
                    yield p
                else:
                    found = True


def evaluate(ref, pred, type_sim, arg_sim):
    redundant = set(pred_redundant(ref.relations, pred.relations))
    pred_rels = list(p for p in pred.relations if p not in redundant)
    pairing = MunkresPairing(relation_similarity(type_sim, arg_sim))
    pairs = list(pairing.get_pairs(ref.relations, pred_rels))
    # for p in pairs:
    #     log(str(p.ref))
    #     log(str(p.pred))
    #     log('')
    base = BaseScores(pairs)
    log_scores('Base', base)
    ie = IEScores(pairs, base=base, tp_attr='couples')
    log_scores('IE', ie)
    return base, ie, pairs


if __name__ == '__main__':
    def main():
        _prog, ref_fn, pred_fn = sys.argv
        ref_ds = MergedRefDataset.from_json_file(ref_fn)
        pred_ds = Dataset.from_json_file(pred_fn)
        try:
            base, ie, _pairs = evaluate(ref_ds, pred_ds, standard_type_similarity, standard_arg_similarity)
            print(ie.f_score)
        except ZeroDivisionError:
            log(f'WARNING: nil R/P')
            print(0.0)
    main()