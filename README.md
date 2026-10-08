# Faculty demo pages

One template. One text file per professor in, one web page per professor out.

## The easy way: the page maker

1. Double-click `Start page maker.bat`. A page opens in your browser. Keep the black window open.
2. The left side lists the professors to do. Click "Open university page" for one.
3. Copy everything from their university page, LinkedIn and Google Scholar, and paste it all into the big box.
   The name should be the first line, or type it in the Name field.
4. Choose their photo if you have one.
5. Click "Make page". In about a minute you get their link, with a Copy button.

The list of professors comes from `queue.csv`. Add rows to it for the next batch.

## Daily routine with files (the other way)

1. For each professor, put their files in `inbox/`, all with the same name:
   - `parag-patel.txt`: the text of their university page, copied and pasted. Put the name on the first line.
   - `parag-patel.pdf`: their LinkedIn profile, saved with LinkedIn's More > Save to PDF.
   One of the two is enough; both together give the fullest page.
2. Optional: save their photo beside it with the same name, for example `inbox/parag-patel.jpg`.
3. Run:

   ```
   python profpages.py go
   ```

   Every file in `inbox/` becomes a page, the site is published, and the files move to `inbox/done/`.
4. Open `links.csv`. It lists each professor with their email and page link.
5. Open each new page and check it against the real profile before you email the link.

## The template

Every page uses the design made for Prof. Parag Patel: warm paper, burgundy accent, a framed portrait,
and a career step chart built from the professor's own roles and dates. The chart appears when the text
gives at least three dated academic roles. The look lives in `assets/site.css`, the chart in `assets/site.js`,
and the page structure in `template.py`.

## A hand-made page for one professor

Save a finished HTML file as `custom/<their-page-name>.html`, for example `custom/parag-patel.html`.
That file is served at their link instead of the template. Prof. Patel's Claude Design page is set up this way.

## Fixing a page

Each professor is one file in `data/`. Open it, correct the text, then run `python profpages.py build` to preview
or `python profpages.py deploy` to publish.

To remove a professor, delete their file in `data/` and deploy again.

## Other commands

| Command | What it does |
|---|---|
| `python profpages.py go --no-deploy` | Build the pages without publishing |
| `python profpages.py add --text file.txt --photo pic.jpg` | Add one professor by hand |
| `python profpages.py list` | Show every page and its link |

You can also drop a ready-made `.json` file into `inbox/` in the same shape as the files in `data/`.

## GitHub

This folder is the repo `hkkk27/prof-pages`. Every time a page is made or the site is published, the tool
commits and pushes to `main` by itself, with the professor's name in the commit message. The working lists
(`queue.csv`, `links.csv`), the raw pasted text and the `.env` file are never uploaded.

## The AI step

The script sends the text to a free OpenRouter model once per professor, to sort it into roles, education and awards.
It keeps only what the text itself supports and drops the rest. Without a key it still works, with less structure.
Put the key in a file named `.env` (copy `.env.example`). That file is never uploaded.

## What every page carries

- A footer saying it is a concept demo by Harshit Singh and not an official university page.
- A setting that keeps it out of search engines.
- An "About this demo" block listing what the professor's own input would add.
