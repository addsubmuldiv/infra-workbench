# Terminal keyword highlights

Open **关键词高亮 / Keyword highlights** in the terminal toolbar. The workspace stores the master toggle and up to 20 case-sensitive literal rules. Each rule has editable text (up to 128 UTF-16 code units), color and enable toggle. Text edits apply when the field loses focus; blank or control-character rules are removed. Restore defaults resets all rules and enables highlighting.

Default red Traceback/CUDA out of memory and amber NaN help locate suspicious output. Blue NCCL and green checkpoint/success are informational matches: a match does not prove an error, a completed checkpoint or successful training. Rules apply to all existing sessions and survive app restarts through the shared workspace preference store.

The renderer reads only the visible normal buffer, at most 200 rows and 500 columns, and creates at most 400 decorations. Matching is case-sensitive, per physical display row (a keyword split by terminal wrapping does not match). It maps xterm cells to columns, including wide Unicode and combined glyphs, rather than assuming string offsets equal terminal columns. It never changes terminal output or injects ANSI. Alternate full-screen buffers are excluded. SearchAddon retains its own decorations; keyword decorations use the bottom layer.

Parsed output, scrolling and rendering schedule a bounded refresh at most once per 100 ms. Parsed-write generations invalidate shifted markers even when scrollback is capped and visible text repeats. Refresh and disconnect cleanup dispose owned decorations/markers; they never clear another addon's decorations. No terminal text is sent to AI or a server by this feature.

Validation: `npm test --prefix frontend` and `npm run build --prefix frontend`.
