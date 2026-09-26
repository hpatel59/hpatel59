# J277 worksheet generator

Builds Google-Docs-ready HTML worksheets (DIGITAL + PRINT) from the OCR GCSE J277 textbook:
one "in-chapter questions" doc and one "end of unit exercises" doc per unit.

    export J277_PDF=/path/to/book.pdf
    python3 build.py        # writes out/U{n}_{Questions|Exercises}_{DIGITAL|PRINT}.html

`data/unit*.py` (question transcriptions) and `out/` are not committed because they reproduce
copyrighted textbook content. `ids.tsv` / `index.csv` hold the Google Drive IDs of the uploaded docs.
