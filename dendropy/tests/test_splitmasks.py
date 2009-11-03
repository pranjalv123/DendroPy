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
Splits encoding tests.
"""

import sys
import os
import unittest
import tempfile
from cStringIO import StringIO

from dendropy.utility import messaging
import dendropy
from dendropy import splitcalc
from dendropy import treecalc
from dendropy import treemanip

_LOG = messaging.get_logger(__name__)

class SplitTest(unittest.TestCase):
    def testCollapseConflicting(self):
        taxon_set = dendropy.TaxonSet([str(i+1) for i in range(5)])
        tree_list = dendropy.TreeList(
            istream=StringIO("""
            (5,((4,3),2),1);
            (5,(4,3,2),1);
            (5,((4,3),2),1);
            (5,(4,3),2,1);
            (5,((4,3),2),1);
            (5,4,3,2,1);
            """),
            format="newick",
            taxon_set=taxon_set)
        tree = tree_list[0]
        expected_tree = tree_list[1]
        splitcalc.encode_splits(tree)
        all_cm = tree.seed_node.edge.clade_mask
        split_to_target = 0xA
        treemanip.collapse_conflicting(tree.seed_node, split_to_target, all_cm)
        splitcalc.encode_splits(tree)
        splitcalc.encode_splits(expected_tree)
        self.assertEqual(treecalc.symmetric_difference(tree, expected_tree), 0)

        tree = tree_list[2]
        expected_tree = tree_list[3]
        splitcalc.encode_splits(tree)
        all_cm = tree.seed_node.edge.clade_mask
        split_to_target = 0x3
        treemanip.collapse_conflicting(tree.seed_node, split_to_target, all_cm)
        splitcalc.encode_splits(tree)
        splitcalc.encode_splits(expected_tree)
        self.assertEqual(treecalc.symmetric_difference(tree, expected_tree), 0)

        tree = tree_list[4]
        expected_tree = tree_list[5]
        splitcalc.encode_splits(tree)
        all_cm = tree.seed_node.edge.clade_mask
        split_to_target = 0x5
        treemanip.collapse_conflicting(tree.seed_node, split_to_target, all_cm)
        splitcalc.encode_splits(tree)
        splitcalc.encode_splits(expected_tree)
        self.assertEqual(treecalc.symmetric_difference(tree, expected_tree), 0)


    def testCladeMasks(self):
        tree_list = dendropy.TreeList(
            istream=StringIO("""((t5:0.161175,t6:0.161175):0.392293,((t4:0.104381,(t2:0.075411,t1:0.075411):1):0.065840,t3:0.170221):0.383247);"""),
            format="newick")
        for i in tree_list:
            _LOG.debug(i.get_indented_form())
            splitcalc.encode_splits(i)
            _LOG.debug(i.get_indented_form(splits=True))
            i.debug_check_tree(splits=True, logger_obj=_LOG)
        root1 = tree_list[0].seed_node
        root1e = root1.edge
        self.assertEqual(splitcalc.split_to_list(root1e.clade_mask), range(6))
        self.assertEqual(splitcalc.split_to_list(root1e.clade_mask, one_based=True), range(1,7))
        self.assertEqual(splitcalc.split_to_list(root1e.clade_mask, mask=21, one_based=True), [1, 3, 5])
        self.assertEqual(splitcalc.split_to_list(root1e.clade_mask, mask=21), [0, 2, 4])
        self.assertEqual(splitcalc.count_bits(root1e.clade_mask), 6)

        fc1 = root1.child_nodes()[0]
        fc1e = fc1.edge
        self.assertEqual(splitcalc.split_to_list(fc1e.clade_mask), [0, 1])
        self.assertEqual(splitcalc.split_to_list(fc1e.clade_mask, one_based=True), [1, 2])
        self.assertEqual(splitcalc.split_to_list(fc1e.clade_mask, mask=0x15, one_based=True), [1])
        self.assertEqual(splitcalc.split_to_list(fc1e.clade_mask, mask=0x15), [0])
        self.assertEqual(splitcalc.count_bits(fc1e.clade_mask), 2)

    def testCountBits(self):
        self.assertEqual(splitcalc.count_bits(21), 3)

    def testLowestBitOnly(self):
        for n, expected in enumerate([0, 1, 2, 1, 4, 1, 2, 1, 8, 1, 2, 1, 4, 1, 2, 1, 16]):
            self.assertEqual(splitcalc.lowest_bit_only(n), expected)

    def testIsTrivial(self):
        y = True
        n = False
        for i, r in enumerate([y, y, y, n, y, n, n, y, y, n, n, y, n, y, y, y, y, y, y, n, y, n, n, y, y, n, n, y, n, y, y, y, ]):
            self.assertEqual(r, splitcalc.is_trivial_split(i, 0xF))
        for i, r in enumerate([y, y, y, n, y, n, n, n, y, n, n, n, n, n, n, y, y, n, n, n, n, n, n, y, n, n, n, y, n, y, y, y, ]):
            self.assertEqual(r, splitcalc.is_trivial_split(i, 0x1F))
                              #0  1  2  3  4  5  6  7  8  9  0  1  2  3  4  5  6  7  8  9  0  1  2  3  4  5  6  7  8  9  0  1
        for i, r in enumerate([y, y, y, n, y, n, n, y, y, y, y, n, y, n, n, y, y, n, n, y, n, y, y, y, y, n, n, y, n, y, y, y, ]):
            self.assertEqual(r, splitcalc.is_trivial_split(i, 0x17))

if __name__ == "__main__":
    unittest.main()