#!/bin/env python
import argparse
import json
from typing import Iterator


AUTO_NORMALIZATION_SUFFIX =  '_AutoNormalization'


def read_json_doc(filename: str, normalization_types: set[str], auto_normalization_types: set[str]) -> dict:
    with open(filename) as f:
        jdoc = json.load(f)
    jdoc['entities_map'] = dict((ent['id'], ent) for ent in jdoc['entities'])
    jdoc['equivalences_map'] = dict((ent, eq) for eq in jdoc['equivalences'] for ent in eq)
    for ent in jdoc['entities']:
        if ent['type'] in auto_normalization_types:
            ent[ent['type'] + AUTO_NORMALIZATION_SUFFIX] = ent['name']
    jdoc['normalization_types'] = normalization_types
    return jdoc


def normalize_form(s: str) -> str:
    return ' '.join(s.split()).lower()


def _equivalent_entities(jdoc: dict, ent: dict) -> Iterator[dict]:
    if ent['id'] in jdoc['equivalences_map']:
        for eid in jdoc['equivalences_map'][ent['id']]:
            yield jdoc['entities_map'][eid]
    else:
        yield ent


def _adequate_entities(jdoc: dict, entity: dict) -> Iterator[dict]:
    for ent in jdoc['entities']:
        if entity['type'] != ent['type']:
            continue
        for norm in jdoc['normalization_types']:
            if norm in entity and norm in ent and entity[norm] == ent[norm]:
                yield from _equivalent_entities(jdoc, ent)


def _adequate_forms(jdoc: dict, entity: dict) -> frozenset[str]:
    return frozenset(normalize_form(ent['name']) for ent in _adequate_entities(jdoc, entity))


def _doc_relation(jdoc: dict, rel:dict) -> tuple:
    source_forms = _adequate_forms(jdoc, jdoc['entities_map'][rel['source']])
    target_forms = _adequate_forms(jdoc, jdoc['entities_map'][rel['target']])
    return rel['type'].lower(), source_forms, target_forms


def doc_relations(jdoc: dict) -> frozenset[tuple]:
    return frozenset(_doc_relation(jdoc, rel) for rel in jdoc['relationships'])


if __name__ == '__main__':
    def main():
        import sys

        parser = argparse.ArgumentParser(
            prog=sys.argv[0],
            description='translates text-bound annotations into document-level relations with adequate argument forms'
        )
        parser.add_argument('filename', help='document to translate')
        parser.add_argument('--normalization-type', action='append', type=str, dest='normalization_types', metavar='NORM', help='normalization type to consider for adequate forms')
        parser.add_argument('--auto-normalization-type', action='append', type=str, dest='auto_normalization_types', metavar='ENT_TYPE', help='generate automatic normalization for entities of the specified type')
        parser.add_argument('--dataset', action='store', type=str, choices=('EPOP',), required=False, default=None, dest='dataset', metavar='DATASET', help='use standard normalizations for the specified dataset')

        options = parser.parse_args()
        if options.dataset is not None:
            if options.dataset == 'EPOP':
                options.normalization_types = {'NCBI_Taxonomy', 'GeoNames'}
                options.auto_normalization_types = {'Disease'}
            else:
                raise RuntimeError('unknown dataset: ' + options.dataset)
        options.normalization_types.update((t + AUTO_NORMALIZATION_SUFFIX) for t in options.auto_normalization_types)

        jdoc = read_json_doc(options.filename, options.normalization_types, options.auto_normalization_types)
        rels = [dict(type=type_, source_names=list(src_names), target_names=list(tgt_names)) for (type_, src_names, tgt_names) in doc_relations(jdoc)]
        json.dump(rels, sys.stdout, indent=4)
        print()

    main()
    
