#!/usr/bin/env python
# AUTHOR: Timothy L. Bailey
# CREATE DATE: 10/10/2010
# PROJECT: MEME suite
# COPYRIGHT: 2010, UQ
#
# DREME -- Discriminative Regular Expression Motif Elicitation
#
import commands, copy, errno, os, os.path, random, re, signal, socket, string 
import subprocess, sys, time
from re import findall, compile, finditer
from math import log, pow, floor, exp
from xml.sax.saxutils import escape
import sequence
from hypergeometric import log_getFETprob
shuffle = __import__('fasta-dinucleotide-shuffle')
hamming = __import__('fasta-hamming-enrich')

#
# turn on psyco to speed up by 3X
# Psyco is not supported by the developer anymore
# so I removed the warning.
#
if __name__=='__main__':
    try:
        import psyco
        psyco.full()
        psyco_found = True
    except ImportError:
        psyco_found = False

# Format for printing very small numbers; used by sprint_logx
_pv_format = "%3.1fe%+04.0f"
_log10 = log(10)

# Arguments to ghostscript minus the -sOutputFile=<png file> <eps file>
_gs_args = ['/usr/bin/gs', '-q', '-r100', '-dSAFER', '-dBATCH', 
        '-dNOPAUSE', '-dDOINTERPOLATE', '-sDEVICE=pngalpha', 
        '-dBackgroundColor=16#FFFFFF', '-dTextAlphaBits=4', 
        '-dGraphicsAlphaBits=4', '-dEPSCrop']
_convert_args = ['/usr/bin/convert']

# Template for EPS motif logo
_template_file = os.path.join('/data/apps/meme/4.9.0/etc', 'template.eps')

# XML Stylesheet transformation program
_xslt_prog = os.path.join('/data/apps/meme/4.9.0/bin', 'xsltproc_lite')

# DREME text stylesheet
_style_to_text = os.path.join('/data/apps/meme/4.9.0/etc', 'dreme-to-text.xsl')

# DREME html stylesheet
_style_to_html = os.path.join('/data/apps/meme/4.9.0/etc', 'dreme-to-html.xsl')

_dna_alphabet = 'ACGT'

_ambig_to_dna = {
        'A' : 'A',
        'C' : 'C',
        'G' : 'G',
        'T' : 'T',
        'R' : 'AG',
        'Y' : 'CT',
        'K' : 'GT',
        'M' : 'AC',
        'S' : 'CG',
        'W' : 'AT',
        'B' : 'CGT',
        'D' : 'AGT',
        'H' : 'ACT',
        'V' : 'ACG',
        'N' : 'ACGT'
        }

# lookup for basic alphabet
_alph = {
        "A" :  1,
        "C" :  1,
        "G" :  1,
        "T" :  1,
}

# order for dynamic programming expansion to ambiguous character
# doubles, triples, N
_dna_ambigs = "RYKMSWBDHVN"

# dynamic programming mappings for ambigs
_dna_ambig_mappings = {
        "R" : "AG",
        "M" : "AC",
        "W" : "AT",
        "Y" : "CT",
        "S" : "CG",
        "K" : "GT",
        "H" : "AY",     # ACT
        "V" : "AS",     # ACG
        "D" : "AK",     # AGT
        "B" : "CK",     # CGT
        "N" : "AB"      # ACGT
}

# verbosity levels
INVALID_VERBOSE, QUIET_VERBOSE, NORMAL_VERBOSE, HIGH_VERBOSE, HIGHER_VERBOSE, DUMP_VERBOSE = range(6)

_verbosity = NORMAL_VERBOSE     # progress output, not debug output


# some globals
neg_freqs = None
unerased_pos_seqs = None
unerased_neg_seqs = None

class TimeoutError(Exception): pass

class MotifComponent(object):
    """Component of a motif.
    """
    def __init__(self, re, p, n, log_pv, log_ev):
        """Construct a MotifComponent"""
        self.re = re
        self.p = p
        self.n = n
        self.log_pv = log_pv
        self.log_ev = log_ev

    def __cmp__(self, other):
        if isinstance(other, MotifComponent):
            if self.log_pv < other.log_pv:
                return -1
            elif self.log_pv > other.log_pv:
                return 1
            elif self.re < other.re:
                return -1
            elif self.re > other.re:
                return 1
            else:
                return 0 # should not happen as re should be unique
        else:
            return super(MotifComponent, self).__cmp__(other)

    def getRE(self):
        return self.re

    def getNSeqsPos(self):
        return self.p

    def getNSeqsNeg(self):
        return self.n

    def getLogPV(self):
        return self.log_pv

    def getPVStr(self):
        return sprint_logx(self.log_pv, 1, _pv_format)

    def getLogEV(self):
        return self.log_ev

    def getEVStr(self):
        return sprint_logx(self.log_ev, 1, _pv_format)

class LogoWriter(object):
    """Writes motif logos"""
    def __init__(self, outdir):
        self.outdir = outdir

    def output_logo(self, pwm, num, re, rc):
        pass

class EPSLogoWriter(LogoWriter):
    """Writes EPS motif logos"""

    def output_logo(self, pwm, num, re, rc):
        rc_str = ("nc", "rc")[rc == True]
        eps_file = os.path.join(self.outdir, 'm{0:02d}{1:s}_{2:s}.eps'.format(
                        num, rc_str, re))
        with open(eps_file, 'w') as eps_fh:
            pwm.writeEPS("DREME", _template_file, eps_fh)

class PNGLogoWriter(LogoWriter):
    """Writes PNG motif logos"""

    def output_logo(self, pwm, num, re, rc):
        rc_str = ("nc", "rc")[rc == True]
        eps_file = os.path.join(self.outdir, 'm{0:02d}{1:s}_{2:s}.eps'.format(
                        num, rc_str, re))
        png_file = os.path.join(self.outdir, 'm{0:02d}{1:s}_{2:s}.png'.format(
                        num, rc_str, re))
        with open(eps_file, 'w') as eps_fh:
            pwm.writeEPS("DREME", _template_file, eps_fh)
        args = []
        if gs_ok():
            args = _gs_args[:]
            args.append('-sOutputFile=' + png_file)
            args.append(eps_file)
        else:
            args = _convert_args[:]
            args.append(eps_file)
            args.append(png_file)
        png_maker = subprocess.Popen(args)
        if (png_maker.wait() != 0):
            print >> sys.stderr, ("Failed to create PNG file. "
                    "Have you got ghostscript installed?")
        os.remove(eps_file)


class BothLogoWriter(LogoWriter):
    """Writes both EPS and PNG motif logos"""

    def output_logo(self, pwm, num, re, rc):
        rc_str = ("nc", "rc")[rc == True]
        eps_file = os.path.join(self.outdir, 'm{0:02d}{1:s}_{2:s}.eps'.format(
                        num, rc_str, re))
        png_file = os.path.join(self.outdir, 'm{0:02d}{1:s}_{2:s}.png'.format(
                        num, rc_str, re))
        with open(eps_file, 'w') as eps_fh:
            pwm.writeEPS("DREME", _template_file, eps_fh)
        args = []
        if gs_ok():
            args = _gs_args[:]
            args.append('-sOutputFile=' + png_file)
            args.append(eps_file)
        else:
            args = _convert_args[:]
            args.append(eps_file)
            args.append(png_file)
        png_maker = subprocess.Popen(args)
        if (png_maker.wait() != 0):
            print >> sys.stderr, ("Failed to create PNG file. "
                    "Have you got ghostscript installed?")

# gets the version of the ghostscript program
_gs_version = []
def gs_version():
    global _gs_version
    if len(_gs_version) != 0:
        return _gs_version;
    gs_path = '/usr/bin/gs'
    if not os.path.exists(gs_path) or not os.access(gs_path, os.X_OK):
        _gs_version = [-1]
    else:
        args = [gs_path, '--version']
        gs = subprocess.Popen(args, stdout=subprocess.PIPE)
        line = gs.stdout.readline()
        gs.stdout.close()
        gs.wait()
        try:
            _gs_version = map(int, line.split('.'))
        except TypeError, ValueError:
            _gs_version = [-1]
    return _gs_version

# returns if a version of ghostscript more modern than 8.15
def gs_ok():
    ver = gs_version()
    if ver[0] > 8:
        return True
    return ver[0] == 8 and len(ver) > 1 and ver[1] > 15
    

# get array of int zeros (numpy is not standard)
def int_zeros(size):
    return [0] * size

# print very large or small numbers
def sprint_logx(logx, prec, format):
    """ Print x with given format given logx.  Handles very large
    and small numbers with prec digits after the decimal.
    Returns the string to print."""
    log10x = logx/_log10
    e = floor(log10x)
    m = pow(10, (log10x - e))
    if ( m + (.5*pow(10,-prec)) >= 10):
        m = 1
        e += 1
    str = format % (m, e)
    return str

def get_strings_from_seqs(seqs):
    """ Extract strings from FASTA sequence records.
        Convert U->T and DNA IUPAC-->N.
    """
    strings = []
    ms = string.maketrans("URYKMBVDHSW", "TNNNNNNNNNN")
    for s in seqs:
        str = s.getString()
        # make upper case and replace all DNA IUPAC characters with N
        # replace U with T
        str = str.upper()
        str = str.translate(ms)
        strings.append(str)
    return strings


def get_rc(re):
    """ Return the reverse complement of a DNA RE.
    """
    return re.translate(string.maketrans("ACGTURYKMBVDHSWN", "TGCAAYRMKVBHDSWN"))[::-1]


def output_best_re(logo_out, xml_out, motif_num, re_pvalues, pos_seqs, minw, maxw, 
        ethresh, log_add_pthresh, given_only):
    """ Output the best RE and the significant words that match it.
        Outputs the PWM for the RE.  PWM is computed from the number
        of sequences containing each significant word composing the RE.
        Returns the best RE, rc, log_pvalue, log_evalue, unerased_log_evalue.
    """
    # get the best RE (lowest p-value) within width range
    candidates = [(re_pvalues[re][4], re) for re in re_pvalues if len(re)>=minw and len(re)<=maxw]
    if len(candidates) == 0:
        return("", "", 1e300, 1e300, 1e300)
    best_re = min(candidates)[1]
    r = re_pvalues[best_re]
    # used to allow 6 for consensus sequences but they shouldn't be created
    assert(len(r) == 5)
    pos = r[0]
    neg = r[2]
    best_log_pvalue = r[4]
    best_log_Evalue = best_log_pvalue + log(len(re_pvalues))
    # get the E-value if there had been no erasing
    unerased_log_pvalue = compute_exact_re_enrichment(best_re, unerased_pos_seqs, 
           unerased_neg_seqs, given_only)
    unerased_log_Evalue = unerased_log_pvalue[4] + log(len(re_pvalues))
    # output the motif if significant
    if best_log_Evalue <= log(ethresh):
        pwm = make_pwm_from_re(best_re, pos_seqs, given_only=given_only)
        # disable timeout as now printing
        disable_timeout()
        # print the best RE
        write_xml_motif(xml_out, motif_num, best_re, pos, neg,
                best_log_pvalue, best_log_Evalue, unerased_log_Evalue, pwm, 
                get_matching_significant_components(best_re, re_pvalues, 
                        log_add_pthresh));
        # output a logo
        logo_out.output_logo(pwm, motif_num, best_re, False)
        # make rc motif
        pwm_rc = copy.deepcopy(pwm).reverseComplement()
        # output a logo
        logo_out.output_logo(pwm_rc, motif_num, get_rc(best_re), True)
    return (best_re, get_rc(best_re), best_log_pvalue, best_log_Evalue, 
            unerased_log_Evalue)


def get_matching_significant_components(best_re, re_pvalues, log_add_pthresh):
    """ Print the words matching RE with significant p-values in order
    of significance.
    """
    # find significant words that match the best RE
    components = []
    # matches on given strand, full width
    m_given = make_dna_re(best_re, True, True)
    for re in re_pvalues:
        match_re = ""
        if m_given.search(re):
            match_re = re
        else:
            rc_re = get_rc(re)
            if m_given.search(rc_re):
                match_re = rc_re
        if match_re and re_pvalues[re][4] < log_add_pthresh:
            r = re_pvalues[re]
            npos = r[0]
            nneg = r[2]
            log_pv = r[4]
            log_ev = log_pv + log(len(re_pvalues))
            components.append(MotifComponent(match_re, npos, nneg, log_pv, 
                            log_ev))
    return components

#def make_and_print_pwm(re, pos_seqs, ev_string, unerased_ev_string, hamming_dist=-1):
#    """ Create an alignment from all non-overlapping matches.
#    Convert to PWM and print the PWM.
#    """
#
#    # make the PWM with no pseudo-count added
#    (pwm, nsites) = make_pwm_from_re(re, pos_seqs, 0, hamming_dist, given_only)
#
#    # print PWM in MEME format
#    alen = len(_dna_alphabet)
#    w = len(re)
#    print "\nMOTIF %s %s\nletter-probability matrix: alength= %d w= %d nsites= %d E= %s" % \
#            (re, ev_string, alen, w, nsites, ev_string)
#    for row in pwm.pretty(): print row
#    print ""
#
#    # print PWM as log-odds matrix for MAST
#    # make the PWM with no pseudo-count 1 added to each cell to avoid log(0)
#    (pwm, nsites) = make_pwm_from_re(re, pos_seqs, 1.0, hamming_dist, given_only)
#    print "log-odds matrix: alength= %d w= %d n= %d bayes= 0 E= %s" % \
#            (alen, w, nsites, ev_string)
#    bkg = [neg_freqs[a] for a in _dna_alphabet]
#    for row in pwm.logoddsPretty(bkg): print row
#    print ""


def make_pwm_from_re(re, seqs, pseudo_count=0.0, hamming_dist=-1, given_only=False):
    """
    Align all non-overlapping matches of the RE on
    either strand of the given sequences.
    Create a PWM from the alignment.
    Returns the PWM and the alignment.
    """

    # get the alignment
    if hamming_dist == -1:
        aln = get_alignment_from_re(re, seqs, given_only)
    else:
        aln = hamming.get_aln_from_word(re, 0, hamming_dist, seqs, given_only)

    # make the PWM
    pwm = sequence.PWM(sequence.getAlphabet('DNA'))
    pwm.setFromAlignment(aln, pseudo_count)

    return pwm


def get_alignment_from_re(re, seqs, given_only):
    """
    Align all non-overlapping matches of the RE on
    either strand of the given sequences.
    Returns the alignment.
    """

    # get the alignment and make into a PWM
    aln = []                                # save matching words for PWM
    m_both = make_dna_re(re, given_only)    # matches on both strands if needed
    m_given = make_dna_re(re, True)         # matches on given strand
    for seqstr in seqs:
        # scan with m_both to insure only non-overlapping matches found
        matches = findall(m_both, seqstr)
        for m in matches:
            # add the match on the correct strand to the alignment
            if m_given.search(m):
                aln.append(m)
            else:
                aln.append(get_rc(m))
    return aln

def get_best_offset(re, seqs):
    """ Get the most common position of the RE in the sequences.
    """
    # make RE
    m_given = make_dna_re(re, True)         # matches on given strand
    counts = []
    for s in seqs:
        if len(counts) < len(s):
            counts.extend(int_zeros(len(s)-len(counts)))
        for m in finditer(m_given, s):
            offset = m.start()
            counts[offset] += 1
    # get the maximum
    best_offset = max( [ (counts[offset],offset) for offset in range(len(counts)) ] )[1]
    return(best_offset)


def print_words(word_pvalues):
    """ Print out the significantly enriched words.
        Input is a dictionary produced by apply_fisher_test.
    """
    print >> sys.stdout, "\n# ORIGINAL VALUES\n# WORD\tRC_WORD\tp\tP\tn\tN\tp-value\tE-value"

    sorted_keys = sorted_re_pvalue_keys(word_pvalues)
    for word in sorted_keys:
        r = word_pvalues[word]
        # get reverse complement of word
        rc_word = get_rc(word)
        # make ambiguous characters lower case for ease of viewing
        word = word.translate(string.maketrans("RYKMBVDHSWN", "rykmbvdhswn"))
        rc_word = rc_word.translate(string.maketrans("RYKMBVDHSWN", "rykmbvdhswn"))
        # print the values after erasing
        log_pvalue = r[4]
        log_Evalue = log_pvalue + log(len(word_pvalues))
        pv_string = sprint_logx(log_pvalue, 1, _pv_format)
        ev_string = sprint_logx(log_Evalue, 1, _pv_format)
        dist_str = ""
        if get_type(r) == "consensus": dist_str = "distance= " + str(r[5])
        print >> sys.stdout, "%s %s %6d %6d %6d %6d %s %s %s" % \
                (word, rc_word, r[0], r[1], r[2], r[3], pv_string, ev_string, dist_str)


def apply_fisher_test(pos_sequence_counts, neg_sequence_counts, P, N):
    """ Apply Fisher test to each word in the positive set
    to test if the number of sequences containing it is
    enriched relative to the negative set.
    Assumes the first two arguments are the outputs of
    count_seqs_with_words.
            P = number of positive sequences
            N = number of negative sequences
    Returns a dictionary indexed by word containing
            [p, P, n, N, log_pvalue]
    where:
            p = number of positive sequences with word
            P = number of positive sequences
            n = number of negative sequences with word
            N = number of negative sequences
            pvalue = Pr(word in >= k positive sequences)
    """

    results = {}

    # loop over words in positive sequences
    for word in pos_sequence_counts:
        p = pos_sequence_counts[word][0]
        if (neg_sequence_counts.has_key(word)):
            n = neg_sequence_counts[word][0]
        else:
            n = 0

        # see if word is enriched in positive set
        log_pvalue = getLogPvalue(p, P, n, N)

        # save result in dictionary
        results[word] = [p, P, n, N, log_pvalue]

    # return dictionary
    return results


def getLogPvalue(p, P, n, N):
    """ Return log of hypergeometric pvalue of #pos >= p
            p = positive successes
            P = positives
            n = negative successes
            N = negatives
    """
    # check that p-value is less than 0.5
    # if p/float(P) > n/float(N):
    if (p * N > n * P):
        # apply Fisher Exact test (hypergeometric p-value)
        log_pvalue = log_getFETprob(N-n, n, P-p, p)[4];
    else:
        log_pvalue = 0          # pvalue = 1

    return log_pvalue


def count_seqs_with_words(seqs, minw, maxw, given_only=False):
    """
    Count the number of FASTA sequences that have each word
    appearing at least once in some sequence.  The sequences are
    passed in as *strings*.

    Words with widths in the range [minw, maxw] are counted.

    Unless given_only==True,
    a sequence is counted as having a word if it contains either
    the word or its reverse-complement, and the count is kept for
    the alphabetically smaller of the two.

    Words containing an ambiguous character are skipped.

    Returns a dictionary indexed by word:
            [seq_count, last_seq]
    where
            seq_count = number of sequences with the word
            last_seq = largest index in sequence array with the word
    """

    seqs_with_words = {}

    # loop over all word widths
    for w in range(minw, maxw+1):

        # loop over all sequences
        seq_no = 0
        for s in seqs:
            seq_no += 1                             # index of current sequence
            slen = len(s)

            # loop over all words in current sequence
            for i in range(0, slen-w+1):
                # get the current word
                word = s[i : i+w];
                # skip word if it contains an ambiguous character
                if (1 in [c in word for c in "nN"]):
                    continue
                # count the number of sequences containing each word in list
                update_seqs_with_words(seqs_with_words, word, seq_no, 
                        given_only)

    # return the dictionary of sequence counts
    return seqs_with_words


def update_seqs_with_words(seqs_with_words, word, seq_no, given_only):
    """ Update the counts of sequences containing given word given
        that sequence number seq_no contains the word.

        Changes the entry for the word in the list seqs_with_words.
    """

    # get alphabetically first of word/rc_word
    if not given_only:
        word = min(word, get_rc(word))

    # update count of sequences for this word
    if (seqs_with_words.has_key(word)):
        # old word
        if (seqs_with_words[word][1] < seq_no):
            # first time seen in this sequence
            values = seqs_with_words[word]
            # increment sequence count
            seqs_with_words[word][0] = values[0] + 1
            # set sequence number
            seqs_with_words[word][1] = seq_no
    else:
        # brand new word
        seqs_with_words[word] = [1, seq_no]


def re_generalize(re, re_pvalues, alph, ambigs, ambig_mappings, 
        new_re_pvalues, log_add_pthresh, given_only):
    """ Expand an RE to all REs with one additional ambiguous character.
    Uses entries in re_pvalues dictionary.
    Add expansions to new_re_pvalues dictionary.
    """

    # adjust p-values for multiple tests
    #log_adjust = log(len(re_pvalues))

    # get numbers of positive and negative sequences
    value = re_pvalues[re]
    P = value[1]
    N = value[3]

    for i in range(0, len(re)):
        # skip columns in RE that are already ambiguous characters
        if not alph.has_key(re[i]):
            continue

        # This array has a key of one letter for speed
        c_counts = {}

        # Get table of counts/p-value records for all identical
        # REs except for primary alphabet character in column "i"
        for k in alph:
            new_re = re[:i] + k + re[i+1:]
            if (given_only):
              # use RE as key if only searching given strand
              index = new_re
            else:
	      # use alphabetically smaller of RE and rc(RE) as key if searching both
              index = min(new_re, get_rc(new_re))
            # only add significant REs to current RE
            #if re_pvalues.has_key(index) and (re_pvalues[index][4] + log_adjust) < log_add_pthresh:
            if re_pvalues.has_key(index) and re_pvalues[index][4] < log_add_pthresh:
                c_counts[k] = (re_pvalues[index][0], re_pvalues[index][2])

        # Build up the table of c_count records for # REs that are
        # identical except have an ambiguous character in column "i".
        # The order is important because we are doing dynamic programming here.
        for ambig in ambigs:
            pair = ambig_mappings[ambig]
            if c_counts.has_key(pair[0]) and c_counts.has_key(pair[1]):
                # combine sequence counts for two REs:
                # size of union minus expected size of intersection
                p1, n1 = c_counts[pair[0]]
                p2, n2 = c_counts[pair[1]]
                p = int(round((p1 + p2) - float(p1*p2)/P))
                n = int(round((n1 + n2) - float(n1*n2)/N))
                c_counts[ambig] = (p, n)

        # add the generalized REs to the positive and negative count arrays
        for k in c_counts:
            # Only generalize to ambiguous characters.  Want to always have one
            # more ambig after this function.
            if not alph.has_key(k):
                # get counts for RE with new ambig "k"
                (p, n) = c_counts[k]
                # compute p-value of counts
                log_pvalue = getLogPvalue(p, P, n, N)
                # create the RE with ambiguous character "k"
                new_re = re[:i] + k + re[i+1:]
                # don't allow N in first or last position
                if (new_re[0] == 'N') or (new_re[-1] == 'N'): continue
                rc_new_re = get_rc(new_re)
		if (given_only):
                  # use RE as key if only searching given strand
		  index = new_re
		else:
		  # use alphabetically smaller of RE and rc(RE) as key if searching both
		  index = min(new_re, get_rc(new_re))
                # save in dictionary
                new_re_pvalues[index] = [p, P, n, N, log_pvalue]
                #print >> sys.stderr, index, [p, P, n, N, log_pvalue]


def sorted_re_pvalue_keys(re_pvalues):
    """ Return the keys of a p-value dictionary, sorted by increasing p-value """
    if not re_pvalues:
        return []
    keys = re_pvalues.keys()
    keys.sort( lambda x, y: cmp(re_pvalues[x][4], re_pvalues[y][4]) or cmp(x,y) )
    return keys


def re_generalize_all(re_pvalues, ngen, log_add_pthresh, maxw, alph, ambigs, 
        ambig_mappings, pos_seqs, neg_seqs, given_only):
    #
    # Generalize all significant REs (maximum ngen).
    #

    # save the input list
    initial_re_pvalues = re_pvalues

    # create the output list
    final_re_pvalues = {}

    old_re_pvalues = re_pvalues
    for n_ambigs in range(1, maxw+1):
        n_re = len(old_re_pvalues)
        if n_re == 0:
            break # All done if RE dictionary is empty
        if _verbosity >= NORMAL_VERBOSE:
            print("Generalizing top {0:d} of {1:d} REs "
                    "to {2:d} ambiguous characters...".format(
                            min(ngen, n_re), n_re, n_ambigs))
        new_re_pvalues = {}
        sorted_keys = sorted_re_pvalue_keys(old_re_pvalues)
        # generalize up to ngen REs
        for re in sorted_keys[:ngen]:
            if n_ambigs > len(re):
                continue # RE too short
            re_generalize(re, old_re_pvalues, alph, ambigs, ambig_mappings, 
                    new_re_pvalues, log_add_pthresh, given_only)

        # add the new REs to the final list
        for key in new_re_pvalues:
            final_re_pvalues[key] = new_re_pvalues[key]

        # use new RE list in next iteration
        old_re_pvalues = new_re_pvalues

    # Compute the pvalues for top ngen hits by counting the number of matches.
    compute_top_res(final_re_pvalues, ngen, pos_seqs, neg_seqs, given_only)

    # Add the pvalues records to the final list.
    for key in initial_re_pvalues:
        final_re_pvalues[key] = initial_re_pvalues[key]

    # return the final list of pvalues
    return final_re_pvalues


def inverse_dna_ambig_mapping():
    inverse_map = {}
    alphabet = _dna_alphabet + _dna_ambigs
    for c in alphabet:
        inverse_map[_ambig_to_dna[c]] = c
    return inverse_map


def re_extend_cores(re_pvalues, ngen, mink, maxk, maxw, log_add_pthresh, 
        nref, use_consensus, pos_seqs, neg_seqs, given_only):
    """
    Pad best RE on each side to maximum width and get alignment.
    Find enriched REs in each flank.
    Combine best primary and secondary REs.
    Refine combined RE.
    New REs added to re_pvalues dictionary.
    """

    # Get best core RE.
    (prim_pvalue, prim_re) = min([ (re_pvalues[re][4], re) for re in re_pvalues] )
    if _verbosity >= NORMAL_VERBOSE:
        prim_pvalue_str = sprint_logx(prim_pvalue, 1, _pv_format)
        print("Extending primary RE {0:s} (p={1:s}) to width {2:d}".format(
                        prim_re, prim_pvalue_str, maxw))

    w = len(prim_re)
    pad = max(mink, maxw - w)
    pad = maxw - w
    # Expand by finding secondary RE in flanking regions if regions wide enough.
    if pad >= mink:
        re = find_best_secondary_re(prim_re, pad, mink, maxk, ngen, 
                log_add_pthresh, use_consensus, pos_seqs, neg_seqs, given_only)
    else:
        re = prim_re

    # Pad RE out to maxw evenly on both sides.
    pad = maxw - len(re)
    left_pad = pad/2
    right_pad = pad - left_pad
    re = (left_pad * 'N') + re + (right_pad * 'N')

    # Do branching search to refine RE.
    if use_consensus:
        refine_from_consensus(re_pvalues, re, nref, pos_seqs, neg_seqs, given_only)
    else:
        refine_from_re(re_pvalues, re, nref, pos_seqs, neg_seqs, given_only)
    #FIXME: trim Ns from ends?


def find_best_secondary_re(prim_re, pad, mink, maxk, ngen, log_add_pthresh, use_consensus, pos_seqs, neg_seqs, given_only):

    # Pad the RE with Ns on both sides.
    w = len(prim_re)
    prim_re_padded = (pad * 'N') + prim_re + (pad * 'N')

    # Get the alignments of all non-overlapping regions matching the core.
    pos_aln = get_alignment_from_re(prim_re_padded, pos_seqs, given_only)
    neg_aln = get_alignment_from_re(prim_re_padded, neg_seqs, given_only)

    # Find secondary REs in left and right flanks of aligned regions.
    # Matches to new REs must all be on the same strand of aligned regions.
    pos_left_flank = [s[:pad] for s in pos_aln]
    pos_right_flank = [s[w+pad:] for s in pos_aln]
    neg_left_flank = [s[:pad] for s in neg_aln]
    neg_right_flank = [s[w+pad:] for s in neg_aln]
    if _verbosity >= NORMAL_VERBOSE:
        print "Finding secondary RE in left flank..."
    left_re_pvalues = re_find_cores(pos_left_flank, neg_left_flank, ngen, mink, maxk, log_add_pthresh, given_only)
    if _verbosity >= NORMAL_VERBOSE:
        print "Finding secondary RE in right flank..."
    right_re_pvalues = re_find_cores(pos_right_flank, neg_right_flank, ngen, mink, maxk, log_add_pthresh, given_only)

    #
    # Get best secondary RE and its best spacing from primary RE.
    #
    # Try left:
    (left_pvalue, left_re) = min([ (left_re_pvalues[re][4],re) for re in left_re_pvalues] )
    left_offset = get_best_offset(left_re, pos_left_flank)
    left_pad = pad - len(left_re) - left_offset
    if _verbosity >= NORMAL_VERBOSE:
        print "Best left p-value is %s (p=%s off=%d pad=%d)" % \
            (sprint_logx(left_pvalue, 1, _pv_format), left_re, left_offset, left_pad)

    # Try right:
    (right_pvalue, right_re) = min([ (right_re_pvalues[re][4],re) for re in right_re_pvalues] )
    right_offset = get_best_offset(right_re, pos_right_flank)
    right_pad = right_offset
    if _verbosity >= NORMAL_VERBOSE:
        print "Best right p-value is %s (p=%s off=%d pad=%d)" % \
            (sprint_logx(right_pvalue, 1, _pv_format), right_re, right_offset, right_pad)

    # Determine best secondary RE.
    (scnd_re, scnd_pad, scnd_pvalue, flank_seqs, scnd_side) = (left_re, left_pad, left_pvalue, pos_left_flank, 'left')
    if right_pvalue < left_pvalue:
        (scnd_re, scnd_pad, scnd_pvalue, flank_seqs, scnd_side) = (right_re, right_pad, right_pvalue, pos_right_flank, 'right')
    if _verbosity >= NORMAL_VERBOSE:
        print "Best secondary RE %s (p=%s side= %s space= %d)" % \
            (scnd_re, sprint_logx(scnd_pvalue, 1, _pv_format), scnd_side, scnd_pad)

    # Combine the primary with the best secondary RE
    if (use_consensus):
        # get the consensus from the RE
        prim_re = get_consensus_from_re(prim_re, pos_seqs)
        scnd_re = get_consensus_from_re(scnd_re, flank_seqs)
    if (scnd_side == 'left'):
        new_re = scnd_re + (scnd_pad * 'N') + prim_re
    else:
        new_re = prim_re + (scnd_pad * 'N') + scnd_re

    return new_re


def refine_from_consensus(re_pvalues, consensus, nref, pos_seqs, neg_seqs, given_only):
    """
    Use the heuristic for finding likely better Hamming-1 neighbors
    to refine the consensus formed from two REs.
    """

    # get optimum Hamming distance from the consensus
    (dist, log_pvalue, p, P, n, N, aln) = hamming.get_best_hamming_alignment(consensus, pos_seqs, neg_seqs, given_only)
    if _verbosity >= NORMAL_VERBOSE:
        print "Best consensus %s distance %d (p=%s)" % \
            (consensus, dist, sprint_logx(log_pvalue, 1, _pv_format))

    # Do one step of "EM-like" alignment to get rid of Ns in consensus
    # This step is IMPORTANT.  Without it, the refinement below may fail.
    consensus = get_consensus_from_aln(aln)
    (dist, log_pvalue, p, P, n, N, aln) = hamming.get_best_hamming_alignment(consensus, pos_seqs, neg_seqs, given_only)
    if _verbosity >= NORMAL_VERBOSE:
        print "Best consensus after EM-like step %s distance %d (p=%s)" % \
            (consensus, dist, sprint_logx(log_pvalue, 1, _pv_format))

    # Refine the consensus using heuristically estimated Hamming-1 neighbors
    candidate_pvalues = {}
    candidate_pvalues[min(consensus, get_rc(consensus))] = [p, P, n, N, log_pvalue, dist]
    re_refine_all(re_pvalues, candidate_pvalues, nref, "", pos_seqs, neg_seqs, dist, given_only)
    (log_pvalue, consensus) = min([ (re_pvalues[cons][4], cons) for cons in re_pvalues] )
    if _verbosity >= NORMAL_VERBOSE:
        print "Best refined %s %s (p=%s)" % \
            (get_type(re_pvalues[consensus]), consensus, sprint_logx(log_pvalue, 1, _pv_format))


def refine_from_re(re_pvalues, re, nref, pos_seqs, neg_seqs, given_only):

    # The code below here works---its just very very slow.

    #
    # Try to specialize the RE by removing all letters that don't
    # occur in any positive matches.
    #
    new_re = specialize_using_consensus(re, pos_seqs)
    if new_re != re:
        "Improved RE by removing letters not appearing in positive matches."
    re = new_re

    #
    # Get p-value of new RE.
    #
    new_pvalue = compute_exact_re_enrichment(re, pos_seqs, neg_seqs, given_only)
    if _verbosity >= NORMAL_VERBOSE:
        print "Extended RE is %s (p=%s)..." % (re,  sprint_logx(new_pvalue[4], 1, _pv_format))

    #
    # Refine the new RE allowing all replacements.
    #
    candidate_pvalues = {}
    index = min(re, get_rc(re))
    candidate_pvalues[index] = re_pvalues[index] = new_pvalue
    all_letters = _dna_alphabet + _dna_ambigs
    new_re_pvalues = re_refine_all(re_pvalues, candidate_pvalues, nref, all_letters, pos_seqs, neg_seqs, given_only=given_only)
    (new_pvalue, new_re) = min([ (new_re_pvalues[re][4],re) for re in new_re_pvalues] )
    if _verbosity >= NORMAL_VERBOSE:
        print "Refined RE is %s (p=%s)..." % (new_re,  sprint_logx(new_pvalue, 1, _pv_format))


def get_type(pvalue_record):
    if len(pvalue_record) > 5 and pvalue_record[5] >= 0:
        return "consensus"
    else:
        return "RE"


def get_consensus_from_re(re, seqs, given_only):
    """
    Convert RE to consensus by computing the best alignment and
    using best letter in each column.
    """

    # Convert REs to consensus strings and create combined consensus string.
    (pwm, nsites) = make_pwm_from_re(re, seqs, given_only=given_only)
    return pwm.consensus_sequence()


def get_consensus_from_aln(aln):
    # make the PWM
    pwm = sequence.PWM(sequence.getAlphabet('DNA'))
    pwm.setFromAlignment(aln)
    # convert to consensus
    return pwm.consensus_sequence()


def specialize_using_consensus(re, seqs, given_only):
    """
    Get the consensus matches to an RE in a set of sequences
    and return the most specific RE matching them all.
    """

    new_re = ""
    inverse_map = inverse_dna_ambig_mapping()
    (pwm, nsites) = make_pwm_from_re(re, seqs, given_only=given_only)
    consensus = pwm.consensus()
    for matches in consensus:
        matches.sort()
        ambig = "".join(matches)
        new_re += inverse_map[ambig]

    return new_re


def re_refine_all(re_pvalues, candidate_pvalues, nref, allowed_letters, pos_seqs, neg_seqs, hamming_dist=-1, given_only=False):
    """
    Refine all significant candidate REs (maximum nref).
    Uses a greedy search.  Each possible letter
    substitution is tested for each RE, and then
    the best nref resulting REs are used in the next round.
    """

    # New (partial) RE dictionary.
    new_re_pvalues = {}

    # Make inverse ambig mapping
    inverse_map = inverse_dna_ambig_mapping()

    # Previously specialized REs
    done_re_list = {}

    # Refine the top nref candidate_pvalues.
    improved_re_pvalues = candidate_pvalues

    # Specialize until top REs are previously specialized ones
    step = 0
    while True:
        step += 1

        if _verbosity >= NORMAL_VERBOSE:
            print "%d: Sorting %d REs..." % (step, len(improved_re_pvalues))
        sorted_keys = sorted_re_pvalue_keys(improved_re_pvalues)
        best_re = sorted_keys[0]
        best_pvalue = improved_re_pvalues[best_re][4]
        if _verbosity >= NORMAL_VERBOSE:
            print "Best candidate p-value is %s (%s)" % (sprint_logx(best_pvalue, 1, _pv_format), best_re)
        # get the top nref REs
        candidate_pvalues = {}
        for re in sorted_keys[:nref]:
            candidate_pvalues[re] = improved_re_pvalues[re]
            new_re_pvalues[re] = improved_re_pvalues[re]

        # Refine the top REs
        if hamming_dist == -1:
            improved_re_pvalues = re_refine(re_pvalues, candidate_pvalues, done_re_list, allowed_letters, pos_seqs, neg_seqs, hamming_dist, given_only)
        else:
            improved_re_pvalues = word_refine(re_pvalues, candidate_pvalues, done_re_list, pos_seqs, neg_seqs, given_only)
        if _verbosity >= NORMAL_VERBOSE:
            print "Improved %d REs..." % len(improved_re_pvalues)

        # Add improved REs to list to return.
        for re in improved_re_pvalues:
            new_re_pvalues[re] = improved_re_pvalues[re]

        # Done if no RE improved.
        if len(improved_re_pvalues) == 0:
            break

    # Return the new REs
    return new_re_pvalues


def re_refine(re_pvalues, candidate_pvalues, done_re_list, allowed_letters, pos_seqs, neg_seqs, hamming_dist=-1, given_only=False):
    """
    Refine each candidate RE by greedy search.
    Only letters in the allowed_letters list are tried as substitutes.
    Return REs that were better than their parent.
    """

    improved_re_pvalues = {}

    n_re = len(candidate_pvalues)
    if _verbosity >= NORMAL_VERBOSE:
        print "Refining %d REs..." % (n_re)

    # Refine each RE in candidate list
    for re in candidate_pvalues:

        # skip if we've previously specialized this RE
        if done_re_list.has_key(re):
            if _verbosity >= NORMAL_VERBOSE:
                print "Already refined", re
            continue
        else:
            if _verbosity >= NORMAL_VERBOSE:
                print "Refining RE", re
            done_re_list[re] = 1

        w = len(re)

        # Try replacing each letter with all other letters.
        for i in range(w):
            old_letter = re[i]
            # Try replacing this letter with each possible letter.
            for new_letter in allowed_letters:
                if new_letter == old_letter:
                    continue
                new_re = re[:i] + new_letter + re[i+1:]
                index = min(new_re, get_rc(new_re))
                # if this is a new RE, compute its p-value
                if not re_pvalues.has_key(index):
                    # compute the p-value
                    if hamming_dist == -1:
                        new_pvalue = compute_exact_re_enrichment(new_re, pos_seqs, neg_seqs, given_only)
                    else:
                        (dist, log_pvalue, p, P, n, N, aln) = hamming.get_best_hamming_alignment(new_re, pos_seqs, neg_seqs, given_only)
                        new_pvalue = [p, P, n, N, log_pvalue, dist]

                    # save the new p-value in improved list only if it is better
                    if new_pvalue[4] < re_pvalues[re][4]:
                        improved_re_pvalues[index] = new_pvalue
                    # save the p-value
                    re_pvalues[index] = new_pvalue

    # return the list of REs that were better than their "parent"
    return improved_re_pvalues


def word_refine(re_pvalues, candidate_pvalues, done_list, pos_seqs, neg_seqs, given_only):
    """
    Estimate the number of positive and negative sites after a single
    character change to the word.
    Returns a dictonary containing the new word.
    Adds the new word to re_pvalues dictionary.
    """

    improved_word_pvalues = {}

    n_words = len(candidate_pvalues)
    if _verbosity >= NORMAL_VERBOSE:
        print "Refining %d words..." % (n_words)

    # Refine each WORD in candidate list
    for word in candidate_pvalues:

        # skip if we've previously specialized this word
        if done_list.has_key(word):
            if _verbosity >= NORMAL_VERBOSE:
                print "Consensus", word, "already refined"
            continue
        else:
            if _verbosity >= NORMAL_VERBOSE:
                print "Refining consensus", word, "..."
            done_list[word] = 1

        # get estimated refinements of this word
        (p, P, n, N, log_pvalue, dist) = candidate_pvalues[word]
        (actual_record, estimated_records) = hamming.get_enrichment_and_neighbors(word, "ACGTN", pos_seqs, neg_seqs, given_only)

        # save the exact record in the real p-values dictionary
        re_pvalues[word] = actual_record
        if _verbosity >= NORMAL_VERBOSE:
            print "Actual p-value is %s (%s)" % (sprint_logx(actual_record[4], 1, _pv_format), word)

        # add the records with estimated p-values better than current word's
        for new_word in estimated_records:
            record = estimated_records[new_word]
            if record[4] < actual_record[4]:
                #FIXME : this may never end if estimated pvalues are very low
                rc_new_word = get_rc(new_word)
                index = min(new_word, rc_new_word)
                improved_word_pvalues[index] = record

    return improved_word_pvalues


def compute_top_res(re_pvalues, ncomp, pos_seqs, neg_seqs, given_only):
    """ Compute the exact p-values for the top ncomp entries.
    in the given table by counting hits in the sequences and
    re-computing the p-values.
    """

    if _verbosity >= NORMAL_VERBOSE:
        print("Computing exact p-values for {0:d} REs...".format(
                min(ncomp, len(re_pvalues))))

    # refine top final REs by actually scanning with the RE
    sorted_keys = sorted_re_pvalue_keys(re_pvalues)
    for re in sorted_keys[:ncomp]:
        re_pvalues[re] = compute_exact_re_enrichment(re, pos_seqs, neg_seqs, given_only)


def compute_exact_re_enrichment(re, pos_seqs, neg_seqs, given_only):
    # get numbers of positive and negative sequences matching RE
    (p, n) = count_seqs_matching_iupac_re(re, pos_seqs, neg_seqs, given_only)
    # get numbers of positive and negative sequences
    P = len(pos_seqs)
    N = len(neg_seqs)
    # compute hypergeometric the p-value
    log_pvalue = getLogPvalue(p, P, n, N)
    return(p, P, n, N, log_pvalue)


def count_seqs_matching_iupac_re(re, pos_seqs, neg_seqs, given_only):
    """Count the number of positive and negative sequences matching
    the given RE on either strand.
    """
    ms = make_dna_re(re, given_only)
    p = 0
    for s in pos_seqs:
        if ms.search(s): p += 1
    n = 0
    for s in neg_seqs:
        if ms.search(s): n += 1
    return(p, n)


def make_dna_re(iupac_re, given_only=False, complete=False):
    """ Create an RE program for matching a DNA IUPAC RE """
    #
    # Create a python RE matching on both strands from an IUPAC RE
    #

    # Replace ambiguous IUPAC characters with the character class they match
    RE = ""
    for c in iupac_re:
        RE += '[' + _ambig_to_dna[c] + ']'

    if not given_only:
        # Get the reverse complement of RE and replace IUPAC characters
        rc_iupac_re = get_rc(iupac_re)
        rc_RE = ""
        for c in rc_iupac_re:
            rc_RE += '[' + _ambig_to_dna[c] + ']'
        # RE matching both strands
        RE = RE + "|" + rc_RE

    if complete:
        # must match the entire string
        RE = "^(" + RE + ")$"

    # return the python RE
    return compile(RE)

def find_print(logo_out, xml_out, motif_num, pos_seqs, neg_seqs, ngen, 
        nref, minw, maxw, mink, maxk, log_add_pthresh, ethresh, use_consensus, given_only):
    """
    Find a motif, print it, erase it.
    """

    #
    # Find core REs.
    #
    re_pvalues = re_find_cores(pos_seqs, neg_seqs, ngen, mink, maxk, 
            log_add_pthresh, given_only)

    #
    # Extend core REs to maximum width by finding new cores in flanking regions.
    #
    if (maxw > maxk):
        re_extend_cores(re_pvalues, ngen, mink, maxk, maxw, log_add_pthresh, 
                nref, use_consensus, pos_seqs, neg_seqs, given_only)

    #
    # Print the best word
    #
    (best_word, rc_best_word, best_pvalue, best_Evalue, unerased_log_Evalue) = \
            output_best_re(logo_out, xml_out, motif_num, re_pvalues, pos_seqs, 
                    minw, maxw, ethresh, log_add_pthresh, given_only)
    if _verbosity >= NORMAL_VERBOSE:
        pv_string = sprint_logx(best_pvalue, 1, _pv_format)
        ev_string = sprint_logx(best_Evalue, 1, _pv_format)
        unerased_ev_string = sprint_logx(unerased_log_Evalue, 1, _pv_format)
        print(("Best RE was {0:s} {1:s} p-value= {2:s} E-value= {3:s} "
               "Unerased_E-value= {4:s}").format(best_word, rc_best_word, 
                        pv_string, ev_string, unerased_ev_string))

    return(best_word, rc_best_word, best_pvalue, best_Evalue, re_pvalues)

def erase_re(re, pos_seqs, neg_seqs):
    ens = len(re) * 'N'
    ms = make_dna_re(re)
    for i in range(0, len(pos_seqs)):
        pos_seqs[i] = ms.sub(ens, pos_seqs[i])
    for i in range(0, len(neg_seqs)):
        neg_seqs[i] = ms.sub(ens, neg_seqs[i])



def re_find_cores(pos_seqs, neg_seqs, ngen, minw, maxw, log_add_pthresh, given_only):
    """
    Find enriched REs in a pair of sequence sets by
            1) counting words
            2) generalizing
    Returns the p-value dictionary.
    """

    re_pvalues = {}

    #
    # Count the number of times each word of length [minw,...,maxw] occurs
    # in each of the two input sets of sequences.
    #
    if _verbosity >= NORMAL_VERBOSE:
        print "Counting positive sequences with each word..."
    pos_seq_counts = count_seqs_with_words(pos_seqs, minw, maxw, given_only)
    if _verbosity >= NORMAL_VERBOSE:
        print "Counting negative sequences with each word..."
    neg_seq_counts = count_seqs_with_words(neg_seqs, minw, maxw, given_only)

    #
    # Compute the p-value of the Fisher Exact Test to each word
    # in the positive set, testing if the word is enriched.
    #
    nwords = len(pos_seq_counts)
    if _verbosity >= NORMAL_VERBOSE:
        print "Applying Fisher Exact Test to {0:d} words...".format(nwords)
    word_pvalues = apply_fisher_test(pos_seq_counts, neg_seq_counts, 
            len(pos_seqs), len(neg_seqs))

    #
    # Generalize REs
    #
    re_pvalues = re_generalize_all(word_pvalues, ngen, log_add_pthresh, maxw,
            _alph, _dna_ambigs, _dna_ambig_mappings, pos_seqs, neg_seqs, given_only)

    #
    # return the RE p-value dictionary
    #
    return re_pvalues


def get_probs(seqs, alphabet_string):
    """ Get the observed probabilities of the letters in a set
    of sequences.  Ambiguous characters are ignored.
    Uses an "add-one" prior."""

    freqs = {}
    # initialize with add-one count
    for char in alphabet_string:
        freqs[char] = 1
    # get the frequencies of DNA letters in the sequences
    for seq in seqs:
        for char in seq:
            if freqs.has_key(char):
                freqs[char] += 1
            else:
                freqs[char] = 0         # ambiguous letter
    # get the total number of non-ambiguous letters
    n = 0.0
    for char in alphabet_string:
        n += freqs[char]
    # normalize the probabilities
    probs = {}
    for char in alphabet_string:
        probs[char] = freqs[char]/n

    return probs

def write_xml_dtd(fh):
    """ Write out the DTD. """
    fh.write(
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n"
        "<!DOCTYPE dreme[\n"
        "<!ELEMENT dreme (model, motifs, run_time)>\n"
        "<!ATTLIST dreme version CDATA #REQUIRED release CDATA #REQUIRED>\n"
        "<!ELEMENT model \n"
        "  (command_line, positives, negatives, background, stop, norc, ngen, add_pv_thresh, \n"
        "  seed, host, when, description?)>\n"
        "<!ELEMENT command_line (#PCDATA)>\n"
        "<!ELEMENT positives EMPTY>\n"
        "<!ATTLIST positives \n"
        "  name CDATA #REQUIRED count CDATA #REQUIRED file CDATA #REQUIRED \n"
        "  last_mod_date CDATA #REQUIRED>\n"
        "<!--  \n"
        "  negatives must have a file and last_mod_date specified when the from\n"
        "  attribute is file.\n"
        "-->\n"
        "<!ELEMENT negatives EMPTY>\n"
        "<!ATTLIST negatives \n"
        "  name CDATA #REQUIRED count CDATA #REQUIRED from (shuffled|file) #REQUIRED\n"
        "  file CDATA #IMPLIED last_mod_date CDATA #IMPLIED>\n"
        "<!-- \n"
        "  background allows DNA and RNA (AA is not going to be supported with DREME) \n"
        "  however currently only DNA is implemented. Note that when type is dna the\n"
        "  value for T must be supplied and when the type is rna the value for U must\n"
        "  be supplied. The sum of the frequencies must be 1 (with a small error).\n"
        "-->\n"
        "<!ELEMENT background EMPTY>\n"
        "<!ATTLIST background \n"
        "  type (dna|rna) #REQUIRED\n"
        "  A CDATA #REQUIRED C CDATA #REQUIRED G CDATA #REQUIRED \n"
        "  T CDATA #IMPLIED U CDATA #IMPLIED \n"
        "  from (dataset|file) #REQUIRED \n"
        "  file CDATA #IMPLIED last_mod_date CDATA #IMPLIED>\n"
        "<!ELEMENT stop EMPTY>\n"
        "<!ATTLIST stop \n"
        "  evalue CDATA #IMPLIED count CDATA #IMPLIED time CDATA #IMPLIED>\n"
        "<!ELEMENT norc (#PCDATA)>\n"
        "<!ELEMENT ngen (#PCDATA)>\n"
        "<!ELEMENT seed (#PCDATA)>\n"
        "<!ELEMENT add_pv_thresh (#PCDATA)>\n"
        "<!ELEMENT host (#PCDATA)>\n"
        "<!ELEMENT when (#PCDATA)>\n"
        "<!ELEMENT description (#PCDATA)>\n"
        "<!ELEMENT motifs (motif+)>\n"
        "<!ELEMENT motif (pos+, match+)>\n"
        "<!ATTLIST motif\n"
        "  id CDATA #REQUIRED seq CDATA #REQUIRED length CDATA #REQUIRED \n"
        "  nsites CDATA #REQUIRED p CDATA #REQUIRED n CDATA #REQUIRED\n"
        "  pvalue CDATA #REQUIRED evalue CDATA #REQUIRED unerased_evalue CDATA #REQUIRED>\n"
        "<!--\n"
        "  pos allows DNA and RNA (AA is not going to be supported with DREME)\n"
        "  however current only DNA is implemented. When the type in the background\n"
        "  is 'dna' pos must have a T attribute and when it is 'rna' pos must have a\n"
        "  U attribute\n"
        "-->\n"
        "<!ELEMENT pos EMPTY>\n"
        "<!ATTLIST pos\n"
        "  i CDATA #REQUIRED A CDATA #REQUIRED C CDATA #REQUIRED G CDATA #REQUIRED \n"
        "  T CDATA #IMPLIED U CDATA #IMPLIED>\n"
        "<!ELEMENT match EMPTY>\n"
        "<!ATTLIST match\n"
        "  seq CDATA #REQUIRED p CDATA #REQUIRED n CDATA #REQUIRED \n"
        "  pvalue CDATA #REQUIRED evalue CDATA #REQUIRED>\n"
        "<!ELEMENT run_time EMPTY>\n"
        "<!ATTLIST run_time\n"
        "  cpu CDATA #REQUIRED real CDATA #REQUIRED stop (evalue|count|time) #REQUIRED>\n"
        "]>\n"
    );

def write_xml_top(fh, pos_seq_file, pos_count, neg_seq_file, neg_count, 
                     alph_type, alph_letters, alph_probs, 
                     stop_evalue, stop_count, stop_time, ngen, seed, 
                     add_pv_thresh, description, given_only):
    """ Write out the top of the xml file. """
    in1 = "  ";
    in2 = in1 * 2;
    dfmt = "%a %b %d %H:%M:%S %Z %Y"
    fh.write('<dreme version="4.9.0" '
             'release="Wed Oct  3 11:07:26 EST 2012">\n');
    fh.write(in1 + '<model>\n');
    # write out the command line
    fh.write(in2 + '<command_line>');
    fh.write('dreme');
    space_re = re.compile("\s+")
    for arg in sys.argv[1:]:
        if (space_re.search(arg) != None):
            fh.write(" \"" + arg + "\"");
        else:
            fh.write(" " + arg);
    fh.write('</command_line>\n');
    # write out the positives
    pos_name = string.replace(os.path.splitext(
            os.path.split(pos_seq_file)[1])[0], "_", " ")
    pos_lmod = time.strftime(dfmt, time.localtime(os.path.getmtime(pos_seq_file)))
    fh.write(in2 + '<positives name="' + pos_name + '" count="' + 
             str(pos_count) + '" file="' + pos_seq_file + '" last_mod_date="' + 
             pos_lmod + '" />\n')
    # write out the negatives
    if (neg_seq_file == None):
        fh.write(in2 + '<negatives name="shuffled positive sequences" count="' +
                 str(neg_count) + '" from="shuffled"/>\n')
    else:
        neg_name = string.replace(os.path.splitext(
                os.path.split(neg_seq_file)[1])[0], "_", " ")
        neg_lmod = time.strftime(dfmt, time.localtime(
                os.path.getmtime(neg_seq_file)))
        fh.write(in2 + '<negatives name="' + neg_name + '" count="' + 
                 str(neg_count) + '" from="file" file="' + neg_seq_file + 
                 '" last_mod_date="' + neg_lmod + '" />\n')
    # write the background
    fh.write(in2 + '<background type="' + alph_type + '"')
    for letter in alph_letters:
        fh.write(' {0:s}="{1:.3f}"'.format(letter, alph_probs[letter]))
    fh.write(' from="dataset"/>\n')
    # write the stopping conditions
    fh.write(in2 + '<stop');
    if stop_evalue != None:
        fh.write(' evalue="{0:g}"'.format(stop_evalue))
    if stop_count != None:
        fh.write(' count="{0:d}"'.format(stop_count))
    if stop_time != None:
        fh.write(' time="{0:d}"'.format(stop_time))
    fh.write('/>\n')
    if (given_only):
      fh.write(in2 + '<norc>TRUE</norc>\n')
    else:
      fh.write(in2 + '<norc>FALSE</norc>\n')
    fh.write(in2 + '<ngen>{0:d}</ngen>\n'.format(ngen))
    fh.write(in2 + '<add_pv_thresh>{0:g}</add_pv_thresh>\n'.format(add_pv_thresh))
    fh.write(in2 + '<seed>{0:d}</seed>\n'.format(seed))
    fh.write(in2 + '<host>{0:s}</host>\n'.format(socket.gethostname()))
    fh.write(in2 + '<when>{0:s}</when>\n'.format(time.strftime(dfmt, time.localtime())))
    if description != None:
        # convert into unix new lines
        description = description.replace('\r\n', '\n').replace('\r', '\n');
        # merge multiple blank lines into single blank lines
        description = re.sub(r'\n{3,}', '\n\n', description);
        # removes trailing blank lines
        description = re.sub(r'\n+$', '', description);
        fh.write(in1 + '<description>{0:s}</description>\n'.format(escape(description)))
    fh.write(in1 + '</model>\n')
    fh.write(in1 + '<motifs>\n')

def write_xml_motif(fh, index, name, p, n, log_pv, log_ev, log_uev, pwm, matches):
    """ Write out the motif to the xml file """
    in1 = "  "
    in2 = in1 * 2
    in3 = in1 * 3
    pv_str = sprint_logx(log_pv, 1, _pv_format)
    ev_str = sprint_logx(log_ev, 1, _pv_format)
    uev_str = sprint_logx(log_uev, 1, _pv_format)
    motif_fmt = ('<motif id="m{0:02d}" seq="{1:s}" length="{2:d}"'
            ' nsites="{3:d}" p="{4:d}" n="{5:d}" pvalue="{6:s}"'
            ' evalue="{7:s}" unerased_evalue="{8:s}">\n')
    fh.write(in2 + motif_fmt.format(index, name, pwm.getLen(),
                    pwm.getNSites(), p, n, pv_str, ev_str, uev_str))
    for pos in range(pwm.getLen()):
        fh.write(in3 + '<pos i="{0:d}"'.format(pos+1));
        for sym in pwm.getAlphabet().getSymbols():
            fh.write(' ' + sym + 
                    '="{0:8.6f}"'.format(pwm.getFreq(pos, sym)))
        fh.write('/>\n');
    match_fmt = ('<match seq="{0:s}" p="{1:d}" n="{2:d}" '
            'pvalue="{3:s}" evalue="{4:s}"/>\n')
    matches.sort();
    for match in matches:
        fh.write(in3 + match_fmt.format(match.getRE(), 
                        match.getNSeqsPos(), match.getNSeqsNeg(),
                        match.getPVStr(), match.getEVStr()));
    fh.write(in2 + '</motif>\n');

def write_xml_bottom(fh, start_time, start_clock, stop_cause):
    """ Write out the bottom of the xml file """
    in1 = "  "
    fh.write(in1 + '</motifs>\n')
    time_elapsed = time.time() - start_time
    cpu_elapsed = time.clock() - start_clock
    tm_fmt = '<run_time cpu="{0:.2f}" real="{1:.2f}" stop="{2:s}"/>\n'
    fh.write(in1 + tm_fmt.format(cpu_elapsed, time_elapsed, stop_cause))
    fh.write('</dreme>\n')

def run_xslt(outdir):
    """Create html and text outputs from the xml file"""
    xml = os.path.join(outdir, 'dreme.xml')
    html = os.path.join(outdir, 'dreme.html')
    text = os.path.join(outdir, 'dreme.txt')
    if os.path.exists(_xslt_prog) and os.access(_xslt_prog, os.X_OK):
        if os.path.exists(_style_to_html):
            if _verbosity >= NORMAL_VERBOSE:
                print "Creating HTML file."
            if (subprocess.call([_xslt_prog, _style_to_html, xml, html]) != 0):
                print >> sys.stderr, "Failed to create HTML file."
        else:
            print >> "Failed to find XML stylesheet for transformation into HTML.\n"

        if os.path.exists(_style_to_text):
            if _verbosity >= NORMAL_VERBOSE:
                print "Creating text file."
            if (subprocess.call([_xslt_prog, _style_to_text, xml, text]) != 0):
                print >> sys.stderr, "Failed to create text file."
        else:
            print >> "Failed to find XML stylesheet for transformation into text.\n"
    else:
        print >> sys.stderr, "Failed to find program for transforming XML into HTML or text.\n"

def timeout_handler(signum, frame):
    raise TimeoutError()
def enable_timeout(max_time, start_time):
    if (max_time != None):
        elapsed = time.time() - start_time
        remaining = max_time - elapsed
        if (remaining < 0):
            raise TimeoutError();
        else:
            signal.alarm(int(remaining));
def disable_timeout():
    signal.alarm(0)

def main():
    #
    # defaults
    #
    outdir = "dreme_out"
    clobber = True
    use_consensus = False
    minw = -1                       # minumum motif width
    maxw = -1                       # maximum motif width
    mink = 3                        # minimum width of core
    maxk = 8                        # maximum width of core
    ngen = 100                      # beam width for generalization
    nref = 1                        # beam width for refinement
    seed = 1                        # random seed
    add_pthresh = 0.01              # minimum p-value to add word to RE
    ethresh = 0.05                  # E-value stopping criterion
    max_motifs = None               # no nmotifs stopping criterion
    max_time = None                 # no maximum running time
    pos_seq_file_name = None        # no positive sequence file specified
    neg_seq_file_name = None        # no negative sequence file specified
    description = None              # description
    description_file = None         # description file
    print_all = False               # don't print long list
    png_out = False                 # output png logos
    eps_out = False                 # output eps logos
    xslt_out = True                 # create outputs using xslt
    logo_out = None
    given_only = False              # score both strands
    global _verbosity               # don't create a new local variable


    #
    # get command line arguments
    #
    usage = """USAGE:
    %s [options]

    -o  <directory>         create the specified output directory 
                            and write all output to files in that directory
    -oc <directory>         create the specified output directory 
                            overwritting it if it already exists;
                            default: create dreme_out in the currrent
                            working directory
    -p <filename>           positive sequence file name (required)
    -n <filename>           negative sequence file name (optional);
                            default: the positive sequences are shuffled
                            to create the negative set if -n is not used
    -norc                   search given strand only for motifs (not reverse complement)
    -e <ethresh>            stop if motif E-value > <ethresh>;
                            default: %g
    -m <m>                  stop if <m> motifs have been output;
                            default: only stop at E-value threshold
    -t <seconds>            stop if the specified time has elapsed;
                            default: only stop at E-value threshold
    -g <ngen>               number of REs to generalize; default: %d
                            Hint: Increasing <ngen> will make the motif
                            search more thoroughly at some cost in speed.
    -s <seed>               seed for shuffling sequences; ignored
                            if -n <filename> given; default: %d
    -v <verbosity>          1..5 for varying degrees of extra output
                            default: 2
    -png                    create PNG logos
    -eps                    create EPS logos
    -desc <description>     store the description in the output;
                            default: no description
    -dfile <filename>       acts like -desc but reads the description from
                            the specified file; allows characters that would 
                            otherwise have to be escaped; 
                            default: no description
    -h                      print this usage message

-----------------------Setting Core Motif Width---------------------------------
                   Hint: The defaults are pretty good; making k larger
                         than %s slows DREME down with little other effect.
                         Use these if you just want motifs shorter than %s.
--------------------------------------------------------------------------------
    -mink <mink>            minimum width of core motif; default %d
    -maxk <maxk>            maximum width of core motif; default %d
    -k <k>                  sets mink=maxk=<k>
--------------------------------------------------------------------------------

---------------------Experimental below here; enter at your own risk.-----------
    -l                      print list of enrichment of all REs tested
--------------------------------------------------------------------------------

    DREME Finds discriminative regular expressions in two sets of DNA
    sequences.  It can also find motifs in a single set of DNA sequences,
    in which case it uses a dinucleotide shuffled version of the first
    set of sequences as the second set.

    DNA IUPAC letters in sequences are converted to N, except U-->T.

    IMPORTANT: If a negative sequence file is given, the sequences
    in it should have exactly the same length distribution as the 
    sequences in the positive sequence file.  (E.g., all sequences
    in both files could have the same length, or each sequence in
    the positive file could have exactly N corresponding sequences with
    the same length as it in in the negative file.)  
    Failure to insure this will cause DREME to fail to find motifs or 
    to report inaccurate E-values.

    """ % (sys.argv[0], ethresh, ngen, seed, maxk, maxk, mink, maxk)

    # Hide these switches---not supported.
    experimental = """
-----------------------Setting Final Motif Width--------------------------------
                   Hint: Making <w> (or <maxw>) larger than <maxk> really
                         slows DREME down, but will allow it to find motifs
                         wider than 7.
--------------------------------------------------------------------------------
    -minw <minw>            minimum word width; default: %d
    -maxw <maxw>            maximum word width; default: %d
    -w <w>                  sets maxw=minw=<w>
--------------------------------------------------------------------------------

---------------------Experimental below here; enter at your own risk.-----------
    -a <add_pthresh>        RE must have this p-value to be added to
                            RE during expansion; default: %g
    -r <nref>               number of REs to refine; default: %d
    -c                      convert REs longer than <maxk> to consensus
                            sequence and refine; default: refine REs
--------------------------------------------------------------------------------
    """
    # % (sys.argv[0], ethresh, ngen, seed, mink, maxk, minw, maxw, 
    #       add_pthresh, nref)

    # no arguments: print usage
    if len(sys.argv) == 1:
        print >> sys.stderr, usage; sys.exit(1)

    # parse command line
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if (arg == "-o"):
          clobber = False
          i += 1;
          try: outdir = sys.argv[i]
          except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-oc"):
            clobber = True
            i += 1;
            try: outdir = sys.argv[i]
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-p"):
            i += 1
            try: pos_seq_file_name = sys.argv[i]
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-n"):
            i += 1
            try: neg_seq_file_name = sys.argv[i]
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-norc"):
            given_only = True
        elif (arg == "-c"):
            use_consensus = True
        elif (arg == "-minw"):
            i += 1
            try: minw = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-maxw"):
            i += 1
            try: maxw = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-w"):
            i += 1
            try: minw = maxw = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-mink"):
            i += 1
            try: mink = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-maxk"):
            i += 1
            try: maxk = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-k"):
            i += 1
            try: mink = maxk = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-g"):
            i += 1
            try: ngen = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-r"):
            i += 1
            try: nref = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-e"):
            i += 1
            try: ethresh = float(sys.argv[i])
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-s"):
            i += 1
            try: seed = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-v"):
            i += 1
            try: _verbosity = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
            if not (_verbosity > 0 and _verbosity < 6) :
                print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-a"):
            i += 1
            try: add_pthresh = float(sys.argv[i])
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-m"):
            i += 1
            try: max_motifs = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-t"):
            i += 1
            try: max_time = int(sys.argv[i], 10)
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-desc"):
            i += 1
            try: description = sys.argv[i]
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-dfile"):
            i += 1
            try: description_file = sys.argv[i]
            except: print >> sys.stderr, usage; sys.exit(1)
        elif (arg == "-png"):
            png_out = True
        elif (arg == "-eps"):
            eps_out = True
        elif (arg == "-noxslt"):
            xslt_out = False
        elif (arg == "-l"):
            print_all = True
        elif (arg == "-h"):
            print >> sys.stderr, usage; sys.exit(1)
        else:
            print >> sys.stderr, "Unknown command line argument: " + arg
            sys.exit(1)
        i += 1

    # check that required arguments given
    if (pos_seq_file_name == None):
        print >> sys.stderr, usage; sys.exit(1)

    # reset maxw to minw if maxw not given and minw is larger
    if minw > maxw:
        if maxw == -1:
            maxw = minw # FIXME jj - this assignment looks like a mistake. I suggest max(maxk, minw)
        else:
            print >> sys.stderr, "minw (%d) must not be greater than maxw (%d)" % (minw, maxw); sys.exit(1)

    # initialze width range
    if minw == -1:
        minw = mink
    if maxw == -1:
        maxw = maxk

    if mink > maxk:
        print >> sys.stderr, "mink (%d) must not be greater than maxk (%d)" % (mink, maxk); sys.exit(1)

    # check that core size not larger than maxw
    maxk = min(maxw, maxk)
    mink = min(maxw, mink)

    # keep track of time
    start_time = time.time()
    start_clock = time.clock()

    # make the directory (recursively)
    try:
        os.makedirs(outdir)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            if not clobber:
                print >> sys.stderr, ("output directory (%s) already exists "
                "but DREME was not told to clobber it") % (outdir); sys.exit(1)
        else: raise

    #
    # Read in the positive and negative sequence files, converting to upper case and 
    # returning a list of strings
    #
    if _verbosity >= NORMAL_VERBOSE:
        print "Reading positive sequences", pos_seq_file_name, "..."
    pos_seqs = sequence.convert_ambigs(sequence.readFASTA(pos_seq_file_name, None, True))
    if neg_seq_file_name:
        if _verbosity >= NORMAL_VERBOSE:
            print "Reading negative sequences", neg_seq_file_name, "..."
        neg_seqs = sequence.convert_ambigs(sequence.readFASTA(neg_seq_file_name, None, True))
    else:
        # use dinucleotide-shuffled positive sequences
        if _verbosity >= NORMAL_VERBOSE:
            print "Shuffling positive sequences..."
        random.seed(seed)               # so repeatable!
        neg_seqs = [ shuffle.dinuclShuffle(s) for s in pos_seqs ]

    # get background frequencies of *negative* sequences for use in MAST output
    global neg_freqs
    neg_freqs = get_probs(neg_seqs, _dna_alphabet)

    if (png_out and eps_out):
        logo_out = BothLogoWriter(outdir)
    elif (png_out):
        logo_out = PNGLogoWriter(outdir)
    elif (eps_out):
        logo_out = EPSLogoWriter(outdir)
    else:
        logo_out = LogoWriter(outdir)

    # read the description
    if description_file:
        with open(description_file) as x: 
            description = x.read()

    # open the xml file for writing
    with open(os.path.join(outdir, 'dreme.xml'), 'w') as xml_out:
        write_xml_dtd(xml_out);
        write_xml_top(xml_out, pos_seq_file_name, len(pos_seqs), 
                         neg_seq_file_name, len(neg_seqs), 
                         "dna", _dna_alphabet, neg_freqs, 
                         ethresh, max_motifs, max_time, ngen, seed, 
                         add_pthresh, description, given_only);
        #
        # find, erase loop
        #
        unerased_word_pvalues = {}
        global unerased_pos_seqs, unerased_neg_seqs
        unerased_pos_seqs = copy.deepcopy(pos_seqs)
        unerased_neg_seqs = copy.deepcopy(neg_seqs)
        nmotifs = 0
        if (max_time != None):
            signal.signal(signal.SIGALRM, timeout_handler)
        while (True):
            if _verbosity >= NORMAL_VERBOSE:
                print "Looking for motif {0:d}...".format(nmotifs+1)
            word = ""
            rc_word = ""
            pvalue = 0
            Evalue = 0
            word_pvalues = {}
            try:
                enable_timeout(max_time, start_time)
                (word, rc_word, pvalue, Evalue, word_pvalues) = find_print(
                        logo_out, xml_out, nmotifs + 1,
                        pos_seqs, neg_seqs, ngen, nref, minw, maxw, mink, 
                        maxk, log(add_pthresh), ethresh, use_consensus, 
                        given_only)
            except TimeoutError:
                stop_cause = "time"
                break
            # save unerased (original) pvalues for printing later
            if nmotifs == 0:
                unerased_word_pvalues = word_pvalues
            # stop if the motif evalue is too large
            if (Evalue > log(ethresh)):
                stop_cause = "evalue"
                break
            # stop if maximum number of motifs
            nmotifs += 1
            if nmotifs == max_motifs:
                stop_cause = "count"
                break
            # Erase best RE from all sequences if significant
            try:
                enable_timeout(max_time, start_time)
                if (Evalue <= log(ethresh)):
                    if _verbosity >= NORMAL_VERBOSE:
                        print(("Erasing best word ({0:s} {1:s})...").format(
                                word, rc_word))
                    erase_re(word, pos_seqs, neg_seqs)
                disable_timeout()
            except TimeoutError:
                stop_cause = "time"
                break

        if _verbosity >= NORMAL_VERBOSE:
            print "Stopping due to hitting the maximum {0:s}.".format(
                    stop_cause)
            elapsed = time.time() - start_time;
            print("{0:d} motifs with E-value < {1:g} found in "
                    "{2:.1f} seconds.".format(nmotifs, ethresh, elapsed))

        #
        # print the p-values for all words before any erasing
        #
        if print_all:
            print_words(unerased_word_pvalues)
        
        write_xml_bottom(xml_out, start_time, start_clock, stop_cause)

    if xslt_out:
        run_xslt(outdir)
    sys.exit(0)

if __name__ == '__main__': main()