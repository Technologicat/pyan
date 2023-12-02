#!/bin/bash
echo -ne "Pyan architecture: generating architecture.{dot,svg}\n"
python3 -m pyan pyan/*.py --no-defines --uses --colored --annotate --dot -V >architecture.dot 2>architecture.log
dot -Tsvg architecture.dot >architecture.svg
echo -ne "Pyan architecture: generating architecture.{html,graphviz=fdp}\n"
python3 -m pyan pyan/*.py --no-defines --uses \
	--grouped --nested-groups \
	--graphviz-layout fdp \
	--colored --html > architecture.html
