#! /usr/bin/env python

###############################################################################
##  DendroPy Phylogenetic Computing Library.
##
##  Copyright 2009 Jeet Sukumaran and Mark T. Holder.
##
##  This program is free software; you can redistribute it and/or modify
##  it under the terms of the GNU General Public License as published by
##  the Free Software Foundation; either version 3 of the License, or
##  (at your option) any later version.
##
##  This program is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##  GNU General Public License for more details.
##
##  You should have received a copy of the GNU General Public License along
##  with this program. If not, see <http://www.gnu.org/licenses/>.
##
###############################################################################

"""
Wrapper around calls to PAUP*, mainly for testing purposes rather than analysis.
"""

import os
import sys
import subprocess
import tempfile
import re
import csv

import unittest
import dendropy.tests
from dendropy.utility import containers
from dendropy.utility import messaging
_LOG = messaging.get_logger(__name__)

import dendropy
from dendropy import splitcalc

if "PAUP_PATH" in os.environ:
    PAUP_PATH = os.environ["PAUP_PATH"]
else:
    PAUP_PATH = "paup"

###############################################################################
# HIGHER-LEVEL CONVENIENCE AND UTILITY METHODS

def get_split_distribution(tree_filepaths,
                           taxa_filepath,
                           unrooted=True,
                           burnin=0):
    """Returns a SplitDistribution object of splits calculated over
    specified trees"""
    p = PaupRunner()
    p.stage_execute_file(taxa_filepath, clear_trees=True)
    p.stage_list_taxa()
    p.stage_load_trees(tree_filepaths=tree_filepaths, unrooted=unrooted, burnin=burnin)
    p.stage_count_splits()
    p.run()
    taxon_set = p.parse_taxon_set()
    tree_count, bipartition_counts = p.parse_group_freqs()
    sd = build_split_distribution(bipartition_counts,
                                  tree_count,
                                  taxon_set,
                                  unrooted=unrooted)
    return sd

###############################################################################
## PAUP* WRAPPER

class PaupRunner(object):
    """ Wrapper around PAUP* """

    def __init__(self, paup_path=None):
        if paup_path is None:
            self.paup_path = PAUP_PATH
        else:
            self.paup_path = paup_path
        self.commands = []
        self.output = []

    ### WRAPPER OPERATIONS ###

    def run(self):
        """ executes list of commands in PAUP*,
        return results of stdout """
        commands = "\n".join(self.commands) + "\n"
        paup_run = subprocess.Popen(['%s -n' % self.paup_path],
                                    shell=True,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        stdout, stderr = paup_run.communicate(commands)
        results = stdout.split("\n")
        if stderr:
            _LOG.error("\n*** ERROR FROM PAUP ***")
            _LOG.error(stderr)
            _LOG.error("\n*** COMMANDS SENT TO PAUP ***\n")
            _LOG.error(commands)
            sys.exit(1)
        self.output.extend(results)
        return results

    ### PAUP COMMANDS ###

    def stage_list_taxa(self):
        """
        Given a data file in memory, this gets PAUP* to print a list of
        taxa that can be used to build a TaxaBlock later.
        """
        self.commands.append("[!TAXON LIST BEGIN]\ntstatus / full;\n[!TAXON LIST END]\n")

    def stage_count_splits(self, majrule_filepath=None, majrule_freq=0.5):
        """
        Given trees in memory, this composes a command to count the split
        frequencies across the trees as well as a save the majority-rule
        consensus tree if a path is given.
        """
        percent = 100 * majrule_freq
        if majrule_filepath is not None:
            treefile = " treefile=%s replace=yes "
        else:
            treefile = ""
        paup_template = []
        paup_template.append("[!SPLITS COUNT BEGIN]")
        paup_template.append("contree / strict=no %s showtree=no grpfreq=yes majrule=yes percent=%d;" \
            % (treefile, percent));
        paup_template.append("[!SPLITS COUNT END]")
        self.commands.extend(paup_template)

    def stage_execute_file(self,
                             filepath,
                             clear_trees=False):
        """Executes file, optionally clearing trees from file if requested"""
        self.commands.append("execute %s;" % filepath)
        if clear_trees:
            self.commands.append("cleartrees;")

    def stage_deroot(self):
        self.commands.append("deroot;")

    def stage_load_trees(self,
                           tree_filepaths,
                           unrooted=True,
                           burnin=0,
                           mode=7): # keep trees in memory, specify 3 to clear
        """
        Composes commands to load a set of trees into PAUP*, with the specified
        number of burnin dropped. NOTE: Taxa Block must be active.
        """
        if isinstance(tree_filepaths, str):
            raise Exception("expecting list of filepaths, not string")
        if unrooted:
            rooting = "unrooted=yes"
        else:
            rooting = "rooted=yes"
        gettree_template = 'gett file= %%s storebrlens=yes warntree=no %s from=%d mode=%d;' % (rooting, burnin+1, mode)
        paup_template = []
        paup_template.append("set warnreset=no; set increase=auto; set warnroot=no;")
        for tree_filepath in tree_filepaths:
            paup_template.append(gettree_template % tree_filepath)
        self.commands.extend(paup_template)

    ### OUTPUT PARSERS ###

    def parse_taxon_set(self):
        """
        Given PAUP* output that includes a taxon listing as produced by
        `stage_list_taxa`, this parses out and returns a taxon block.
        """
        taxlabels = []
        taxinfo_pattern = re.compile('\s*(\d+) (.*)\s+\-')
        idx = 0
        for line in self.output:
            idx += 1
            if line == "TAXON LIST BEGIN":
                break
        for line in self.output[idx:]:
            if line == "TAXON LIST END":
                break
            ti_match = taxinfo_pattern.match(line)
            if ti_match:
                taxlabels.append(ti_match.group(2).strip())
        taxon_set = dendropy.TaxonSet()
        for taxlabel in taxlabels:
            taxon_set.new_taxon(label=taxlabel)
        return taxon_set

    def parse_group_freqs(self):
        """
        Given PAUP* output that includes a split counting procedure,
        this collects the splits and returns a dictionary of group strings and
        their frequencies
        """
        bipartitions = []
        bipartition_freqs = {}
        bipartition_counts = {}
        tree_count = None
        tree_count_pattern = re.compile('.*Majority-rule consensus of ([\d]*) tree.*', re.I)

        bipartition_section = re.compile('Bipartitions found in one or more trees and frequency of occurrence:')
        bp_full_row_with_perc_col = re.compile('([\.|\*]+)\s+([\d\.]+)\s+([\d\.]*)%')
        bp_full_row_with_no_perc_col = re.compile('([\.|\*]+)\s+([\d\.]+)')
        bp_row = re.compile('([\.|\*]+).*')

        # find tree count
        for idx, line in enumerate(self.output):
            tp_match = tree_count_pattern.match(line)
            if tp_match:
                break
        if not tp_match:
            raise Exception("Failed to find tree count in PAUP* output")
        tree_count = int(tp_match.group(1))

        while not bp_row.match(self.output[idx]):
            idx += 1

        split_idx = 0
        split_reps = {}
        for line in self.output[idx:]:
            if line == "SPLITS COUNT END":
                 break
            bp_match = bp_full_row_with_perc_col.match(line)
            if not bp_match:
                bp_match = bp_full_row_with_no_perc_col.match(line)
            if bp_match:
                # full row, or end of partial rows
                if len(split_reps) == 0:
                    split_rep = bp_match.group(1)
                else:
                    split_rep = split_reps[split_idx] + bp_match.group(1)
                bipartition_counts[split_rep] = int(bp_match.group(2))
                split_idx += 1
            else:
                # either (1) partial row or (2) break between sections
                bp_match = bp_row.match(line)
                if not bp_match:
                    split_idx = 0
                else:
                    if split_idx in split_reps:
                        split_reps[split_idx] += bp_match.group(1)
                    else:
                        split_reps[split_idx] = bp_match.group(1)
                    split_idx += 1
        return tree_count, bipartition_counts

###############################################################################
# UTILITY METHODS

def build_split_distribution(bipartition_counts,
                             tree_count,
                             taxon_set,
                             unrooted=True):
    """
    Returns a populated SplitDistribution object based on the given
    bipartition info.
    """
    sd = splitcalc.SplitDistribution(taxon_set=taxon_set)
    sd.unrooted = unrooted
    sd.total_trees_counted = tree_count
    for g in bipartition_counts:
        sd.add_split_count(paup_group_to_mask(g, normalized=unrooted),
            bipartition_counts[g])
    return sd

def paup_group_to_mask(group_string, normalized=False):
    """
    This converts a PAUP* group representation (i.e. a string of askterisks
    and periods, where the asterisks denote the taxon index counting from
    left to right) to a mask representation:
        - a clade mask, where 1's represent descendents of the split/edge
          (with taxon index counting from right to left, i.e., first taxon
          is right-most bit)
        - a split mask, an unrooted normalized version of the above, where
          if the right most bit is not 1 the clade mask is complemented
          (and not changed otherwise).
    """
    group_string = group_string[::-1] # flip to get correct orientation
    clade_mask = int(group_string.replace("*", "1").replace(".", "0"), 2)
    if normalized:
        mask=((2 ** len(group_string)) -1)
        return containers.NormalizedBitmaskDict.normalize(clade_mask, mask)
    else:
        return clade_mask

###############################################################################
## OLD STUFF
###############################################################################

def bipartitions(data_filepath,
                 tree_filepath,
                 min_clade_freq=0.5,
                 burnin=0,
                 paup_path=PAUP_PATH):
    """
    Given a set of trees (and data file), this uses PAUP*'s contree
    command to calculate the splits (bipartitions) on the trees, as well
    as their counts and relative percentages. Returned is:

        - list of taxon labels, in order of the index assigned to them by PAUP
        - list of bipartition strings in PAUP*'s notation (e.g., "...**.*.*")
        - a dictionary with the bipartition string as a key and the count of the
          bipartition occurrence in the trees examined as values
        - a dictionary with the bipartition string as a key and the
          percentage of trees with the bipartition occurence as values.
    """

    paup_args = {
        'data_filepath': data_filepath,
        'tree_filepath': tree_filepath,
        'percent': min_clade_freq * 100,
        'burnin': burnin+1,
    }
    paup_template = """\
    set warnreset=no;
    set increase=auto;
    exe %(data_filepath)s;
    gett file=%(tree_filepath)s storebrlens=yes warntree=no unrooted=yes;
    tstatus / full;
    contree %(burnin)d-. / strict=no showtree=no grpfreq=yes majrule=yes percent=%(percent)d;
"""
    paup_run = subprocess.Popen(['%s -n' % paup_path],
                                shell=True,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE)
    stdout, stderr = paup_run.communicate(paup_template % paup_args)
    results = stdout.split('\n')
    tax_labels = []
    bipartitions = []
    bipartition_freqs = {}
    bipartition_counts = {}
    bipartition_pattern = re.compile('([\.|\*]+)\s+([\d\.]+)\s+([\d\.]*)%')
    bipartition_pattern2 = re.compile('([\.|\*]+)\s+([\d\.]+)')
    taxinfo_pattern = re.compile('\s*(\d+) (.*)\s+\-')
    for line in results:
        bp_match = bipartition_pattern.match(line)
        if bp_match:
            bipartitions.append(bp_match.group(1))
            bipartition_counts[bp_match.group(1)] = int(bp_match.group(2))
            bipartition_freqs[bp_match.group(1)] = float(bp_match.group(3))
        else:
            bp_match2 = bipartition_pattern.match(line)
            if bp_match2:
                bipartitions.append(bp_match2.group(1))
                bipartition_counts[bp_match2.group(1)] = int(bp_match2.group(2))
                bipartition_freqs[bp_match2.group(1)] = float(bp_match2.group(2))
            else:
                ti_match = taxinfo_pattern.match(line)
                if ti_match:
                    tax_labels.append(ti_match.group(2).strip())
    return tax_labels, bipartitions, bipartition_counts, bipartition_freqs

def estimate_model(char_array,
                   tree_model=None,
                   num_states=6,
                   unequal_base_freqs=True,
                   gamma_rates=True,
                   prop_invar=True,
                   tree_est_criterion="likelihood",
                   tree_user_brlens=True,
                   paup_path='paup'):
    """
    Given a dataset, `char_array`, uses client-supplied tree or estimates a
    tree, and character substitution model for the data.
    Returns a tuple, consisting of a trees block with the tree(s) used for the
    estimated character model, and a dictionary with estimates of rates, kappa,
    base_frequencies, alpha, prop_invar, etc. as well as likelihood.
    """
    ds = dendropy.Dataset()
    paup_args = {
        'nst': num_states,
        'basefreq' : unequal_base_freqs and 'estimate' or 'equal',
        'rates' : gamma_rates and 'gamma' or 'equal',
        'pinvar' : prop_invar and 'estimate' or '0',
    }
    taxab = ds.new_taxon_set(taxon_set=char_array.taxon_set)
    if tree_model is not None:
        assert tree_model.taxon_set is char_array.taxon_set
        treeb = ds.new_tree_list(taxon_set=taxab)
        treeb.append(tree_model)
        tf = tempfile.NamedTemporaryFile()
        ds.write(file=tf, format='nexus', exclude_chars=True, exclude_trees=False)
        tf.flush()
        paup_args['tree'] = "gettrees file=%s storebrlens=yes;" % tf.name
    else:
        if tree_est_criterion == 'nj':
            paup_args['tree'] = 'nj;'
        else:
            paup_args['tree'] = "set crit=%s; hsearch; set crit=like;" % tree_est_criterion
    if tree_user_brlens:
        paup_args['userbrlens'] = 'yes'
    else:
        paup_args['userbrlens'] = 'no'

    char_array.reindex_taxa(taxab)
    charb = ds.add_char_array(char_array=char_array)
    cf = tempfile.NamedTemporaryFile()
    ds.write(file=cf, format='nexus', exclude_chars=False, exclude_trees=True)
    cf.flush()
    paup_args['datafile'] = cf.name

    output_tree_file_handle, output_tree_filepath = tempfile.mkstemp(text=True)
    paup_args['est_tree_file'] = output_tree_filepath

    paup_template = """\
    set warnreset=no;
    exe %(datafile)s;
    set crit=like;
    lset tratio=estimate rmatrix=estimate nst=%(nst)s basefreq=%(basefreq)s rates=%(rates)s shape=estimate pinvar=%(pinvar)s userbrlens=yes;
    %(tree)s;
    lscore 1 / userbrlens=%(userbrlens)s;
    savetrees file=%(est_tree_file)s format=nexus root=yes brlens=yes taxablk=yes maxdecimals=20;
"""
    paup_run = subprocess.Popen(['%s -n' % paup_path],
                                shell=True,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE)
    stdout, stderr = paup_run.communicate(paup_template % paup_args)
    patterns = {
        'likelihood' : re.compile('-ln L\s+([\d\.]+)'),
        'rAC' : re.compile('  AC\s+([\d\.]+)'),
        'rAG' : re.compile('  AG\s+([\d\.]+)'),
        'rAT' : re.compile('  AT\s+([\d\.]+)'),
        'rCG' : re.compile('  CG\s+([\d\.]+)'),
        'rCT' : re.compile('  CT\s+([\d\.]+)'),
        'rGT' : re.compile('  GT\s+([\d\.]+)'),
        'kappa': re.compile('  kappa\s+([\d\.]+)'),
        'prop_invar' : re.compile('P_inv\s+([\d\.]+)'),
        'alpha' : re.compile('Shape\s+([\S]+)'),
        'pA' : re.compile('  A\s+([\d\.]+)'),
        'pC' : re.compile('  C\s+([\d\.]+)'),
        'pG' : re.compile('  G\s+([\d\.]+)'),
        'pT' : re.compile('  T\s+([\d\.]+)'),
    }

    results = {}
    for value_name in patterns:
        results[value_name] = None
    for line in stdout.split('\n'):
        for value_name in patterns:
            m = patterns[value_name].match(line)
            if m:
                results[value_name] = m.group(1)

    for value_name in results:
        if value_name == 'likelihood':
            results[value_name] = -1 * float(results[value_name])
        elif results[value_name] is not None:
            try:
                results[value_name] = float(results[value_name])
            except:
                pass

    est_ds = dendropy.Dataset(file=open(output_tree_filepath, "rU"), format="NEXUS")
    return est_ds.tree_lists[0], results
