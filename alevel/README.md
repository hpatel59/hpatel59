# OCR AS/A Level (H046/H446) worksheet generator

Builds Google-Docs-ready HTML worksheets (DIGITAL + PRINT) from the PG Online OCR AS/A Level
Computer Science textbook: one "in-chapter questions" doc and one "end of chapter exercises"
doc per textbook section (12 sections, 64 chapters), grouped by chapter.

    export AL_PDF=/path/to/book.pdf
    python3 build.py        # writes out/S{nn}_{Questions|Exercises}_{DIGITAL|PRINT}.html

`chapters.py` lists the sections/chapters. `data/s*.py` (question transcriptions) and `out/`
are not committed because they reproduce copyrighted textbook content. `ids.tsv` holds the
Google Drive IDs of the uploaded docs.
