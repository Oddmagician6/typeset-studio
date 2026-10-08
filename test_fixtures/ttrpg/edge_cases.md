# Edge Cases

Each case is introduced by a "Case N" subhead that says what should happen. A Phase 1 test can split this file on those subheads, or parse it whole. Every case must build, lose no words, and pass the two round-trip properties of the rich editor's tests: engine fidelity and model stability. Byte-for-byte equality also holds except where a case says the source is normalised (cases 13 and 19). The prose here avoids underscores and backslashes, because the app reads them as markup even inside backticks.

## Case 1: an empty stat block builds (a name and nothing else)

~~~ statblock name="Nameless Thing"
~~~

## Case 2: a stat block with no attributes at all builds, with no title bar

~~~ statblock
Armor Class: 10
~~~

## Case 3: a score row with five cells is still a score row, with no modifiers worked out (not the six 5e names)

~~~ statblock name="Five Scores"
STR 10 | DEX 10 | CON 10 | INT 10 | WIS 10
~~~

## Case 4: scores at the edges: 1 is -5, 30 is +10, 0 is -5 (clamped by the formula floor, not an error), 31 is +10

~~~ statblock name="Extremes"
STR 1 | DEX 30 | CON 0 | INT 31 | WIS 10 | CHA 11
~~~

## Case 5: a written modifier is kept as written, even if it disagrees with the score

~~~ statblock name="Wrong Modifier"
STR 18 (+1) | DEX 10 (+0) | CON 10 (−0) | INT 10 | WIS 10 | CHA 10
~~~

## Case 6: a non-numeric score makes the line a plain field-less entry, not a score row

~~~ statblock name="Odd Scores"
STR 18 | DEX high | CON 10 | INT 10 | WIS 10 | CHA 10
~~~

## Case 7: a line with pipes that is not a score row: one field when a piece is not Label: value, several fields when every piece is

~~~ statblock name="Pipes"
Speed: 30 ft. | climb 20 ft.
Combat: 45 | Instinct: 60 | Armor: 10
~~~

## Case 8: a field with no value keeps its label

~~~ statblock name="Blank Field"
Senses:
Languages: —
~~~

## Case 9: a colon inside a section is an entry, not a field (only the lines before the first section are fields)

~~~ statblock name="Colons"
Armor Class: 12
--- Actions
Note: this creature never attacks first.
At will: *light*, *mage hand*
~~~

## Case 10: a section line with no name, a lone triple hyphen, and an escaped one

The lone triple hyphen and the one followed by a space are both a bare rule between sections. A backslash before the hyphens makes the line literal text, an entry. None of them is a scene break (inside a fence, scene breaks don't apply), and smart punctuation must not turn them into an em dash before the line is classified.

~~~ statblock name="Rules"
Armor Class: 12
---
--- 
\--- not a section
--- Actions
***Hit.*** It hits.
~~~

## Case 11: emphasis, links and an endnote inside fields and entries

~~~ statblock name="Marked Up"
Languages: *Common*, **Draconic**, [Aquan](https://example.com/aquan)
--- Actions
***Strike.*** It strikes[^strike].
~~~

[^strike]: The strike counts as magical.

## Case 12: names, metas and titles with markup-like characters are escaped, not parsed

~~~ statblock name="Tom & Jerry <the twins>" meta="Small *humanoid*, 50% evil"
Armor Class: 10
~~~

~~~ sidebar title="Rule #1: Don't Panic & Don't Run"
Text with a < and a > and an & in it.
~~~

## Case 13: smart-quoted attribute values (pasted from a word processor) are still read

Today they are not: the attribute pattern only accepts straight quotes, so these attributes are silently dropped, for every block type (a figure's src included). Phase 1 should accept curly quotes, and the round trip then writes straight ones, which is the normalisation this case allows.

~~~ statblock name=“Curly Quotes” meta=“Medium fey”
Armor Class: 13
~~~

## Case 14: a stat block taller than a page splits across pages and loses no line

See the Mere-Wyrm in the stat block corpus on a 5 x 8 trim, and the generated long stat block from the long-book generator.

## Case 15: an empty read-aloud box and an empty sidebar build (a typed empty fence is kept, like a caption-less figure)

~~~ readaloud
~~~

~~~ sidebar title="Empty"
~~~

## Case 16: a read-aloud box with several paragraphs keeps them as paragraphs

~~~ readaloud
First paragraph of boxed text.

Second paragraph of boxed text, which runs on long enough to wrap onto a second line in a single column and a third in two columns.
~~~

## Case 17: a sidebar with no title builds with no title bar

~~~ sidebar
A titleless callout.
~~~

## Case 18: a fence inside a sidebar closes the sidebar (fences don't nest)

This documents current behaviour rather than a wish: the list fence line closes the sidebar, the two items become one ordinary paragraph ("one two"), and the last fence line opens a plain block holding "After the list." The test asserts the build does not crash and no words are lost.

~~~ sidebar title="Nested"
Before the list.
~~~ list
one
two
~~~
After the list.
~~~

## Case 19: a block type in capitals and with extra spaces is the same block (the round trip writes it in lower case with one space, a normalisation)

~~~   StatBlock   name="Shouty"
Armor Class: 10
~~~

~~~ READALOUD
Loud.
~~~

## Case 20: Unicode in names and entries

~~~ statblock name="Ærinþ the Ŵyrmling" meta="Tiny dragon, neutral"
Languages: Ελληνικά, Русский, 日本語
--- Actions
***Kühler Atem.*** Ein Hauch — kalt wie der Winter.
~~~

## Case 21: an unclosed stat block at the end of a chapter is closed by the end of the file

~~~ statblock name="Unclosed"
Armor Class: 10
--- Actions
***Last Word.*** The file ends inside this block.
