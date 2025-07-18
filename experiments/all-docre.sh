CORPORA="EPOP"
SETS="train dev"


SCRIPT=./json2docre.py


for corpus in $CORPORA
do
    for st in $SETS
    do
	    indir=corpus/json/$corpus/$st
	    outdir=corpus/docre/$corpus/$st
	    mkdir -p $outdir
	    for f in $indir/*.json
	    do
	      b=$(basename $f)
  	    $SCRIPT --dataset $corpus $f >$outdir/$b
      done
    done
done

