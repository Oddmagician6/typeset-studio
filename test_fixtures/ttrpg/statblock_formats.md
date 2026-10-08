# Stat Block Formats

One creature, the Bog-Thrall, written in each stat block format the app should accept, most common first (ROADMAP #74, Phase 1). Formats 1 to 3 must read into exactly the same stat block: `statblock_formats.json` holds that model and the per-format expectations. The 2024 layout carries two more facts (initiative and saving throws in the score table), so it has its own expected model. The old-school stat line is a different creature, since that system has no ability scores.

Every block here sits inside a `~~~ statblock` fence, which is where any format is accepted as written. Format 2's two Homebrewery forms also appear once more at the end with no fence, as they would be pasted: the paste and import converter should find them and wrap them in a fence.

The text of each creature is original to this file; the layouts follow each format's published shape.

## Format 1a: the classic 5e layout, bold labels with no colon

As typed in Word or Google Docs, copied from D&D Beyond, or imported from the author's own Word bestiary.

~~~ statblock
**Bog-Thrall**
*Medium undead, unaligned*
**Armor Class** 9
**Hit Points** 26 (4d8 + 8)
**Speed** 25 ft., swim 30 ft.
STR 14 (+2) | DEX 8 (−1) | CON 15 (+2) | INT 3 (−4) | WIS 8 (−1) | CHA 5 (−3)
**Saving Throws** Wis +1
**Damage Immunities** poison
**Condition Immunities** exhausted, poisoned
**Senses** darkvision 60 ft., passive Perception 9
**Languages** understands the languages it knew in life but can't speak
**Challenge** 1/2 (100 XP)
***Peat-Preserved.*** The thrall drops to 1 hit point instead of 0 unless the damage is fire or radiant.
***Called by the Bell.*** While the abbey bell rings, the thrall can't be frightened or charmed.
**Actions**
***Grasping Hands.*** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. *Hit:* 6 (1d8 + 2) bludgeoning damage, and the target is grappled (escape DC 12).
***Drag Under.*** The thrall swims up to its speed, pulling a creature it is grappling with it.
~~~

## Format 1b: the classic layout pasted from a PDF, with no formatting at all

The labels are known 5e labels, so they are found without bold. The scores come out of a PDF as a line of names and a line of values. With no bold, the entry names are found by their full stop: a short phrase at the start of a line, ending in a full stop, in the traits or a section.

~~~ statblock
Bog-Thrall
Medium undead, unaligned
Armor Class 9
Hit Points 26 (4d8 + 8)
Speed 25 ft., swim 30 ft.
STR DEX CON INT WIS CHA
14 (+2) 8 (−1) 15 (+2) 3 (−4) 8 (−1) 5 (−3)
Saving Throws Wis +1
Damage Immunities poison
Condition Immunities exhausted, poisoned
Senses darkvision 60 ft., passive Perception 9
Languages understands the languages it knew in life but can't speak
Challenge 1/2 (100 XP)
Peat-Preserved. The thrall drops to 1 hit point instead of 0 unless the damage is fire or radiant.
Called by the Bell. While the abbey bell rings, the thrall can't be frightened or charmed.
Actions
Grasping Hands. Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 6 (1d8 + 2) bludgeoning damage, and the target is grappled (escape DC 12).
Drag Under. The thrall swims up to its speed, pulling a creature it is grappling with it.
~~~

## Format 2a: Homebrewery, the current (V3) form

~~~ statblock
{{monster,frame
## Bog-Thrall
*Medium undead, unaligned*
___
**Armor Class** :: 9
**Hit Points**  :: 26 (4d8 + 8)
**Speed**       :: 25 ft., swim 30 ft.
___
|  STR  |  DEX  |  CON  |  INT  |  WIS  |  CHA  |
|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
|14 (+2)|8 (−1)|15 (+2)|3 (−4)|8 (−1)|5 (−3)|
___
**Saving Throws**        :: Wis +1
**Damage Immunities**    :: poison
**Condition Immunities** :: exhausted, poisoned
**Senses**               :: darkvision 60 ft., passive Perception 9
**Languages**            :: understands the languages it knew in life but can't speak
**Challenge**            :: 1/2 (100 XP)
___
***Peat-Preserved.*** The thrall drops to 1 hit point instead of 0 unless the damage is fire or radiant.
:
***Called by the Bell.*** While the abbey bell rings, the thrall can't be frightened or charmed.
### Actions
***Grasping Hands.*** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. *Hit:* 6 (1d8 + 2) bludgeoning damage, and the target is grappled (escape DC 12).
:
***Drag Under.*** The thrall swims up to its speed, pulling a creature it is grappling with it.
}}
~~~

## Format 2b: Homebrewery's legacy form, also GM Binder's

~~~ statblock
___
> ## Bog-Thrall
>*Medium undead, unaligned*
> ___
> - **Armor Class** 9
> - **Hit Points** 26 (4d8 + 8)
> - **Speed** 25 ft., swim 30 ft.
>___
>|STR|DEX|CON|INT|WIS|CHA|
>|:---:|:---:|:---:|:---:|:---:|:---:|
>|14 (+2)|8 (−1)|15 (+2)|3 (−4)|8 (−1)|5 (−3)|
>___
> - **Saving Throws** Wis +1
> - **Damage Immunities** poison
> - **Condition Immunities** exhausted, poisoned
> - **Senses** darkvision 60 ft., passive Perception 9
> - **Languages** understands the languages it knew in life but can't speak
> - **Challenge** 1/2 (100 XP)
> ___
> ***Peat-Preserved.*** The thrall drops to 1 hit point instead of 0 unless the damage is fire or radiant.
>
> ***Called by the Bell.*** While the abbey bell rings, the thrall can't be frightened or charmed.
> ### Actions
> ***Grasping Hands.*** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. *Hit:* 6 (1d8 + 2) bludgeoning damage, and the target is grappled (escape DC 12).
>
> ***Drag Under.*** The thrall swims up to its speed, pulling a creature it is grappling with it.
~~~

## Format 3: the colon form (native; forums and plain text)

~~~ statblock name="Bog-Thrall" meta="Medium undead, unaligned"
Armor Class: 9
Hit Points: 26 (4d8 + 8)
Speed: 25 ft., swim 30 ft.
STR 14 | DEX 8 | CON 15 | INT 3 | WIS 8 | CHA 5
Saving Throws: Wis +1
Damage Immunities: poison
Condition Immunities: exhausted, poisoned
Senses: darkvision 60 ft., passive Perception 9
Languages: understands the languages it knew in life but can't speak
Challenge: 1/2 (100 XP)
***Peat-Preserved.*** The thrall drops to 1 hit point instead of 0 unless the damage is fire or radiant.
***Called by the Bell.*** While the abbey bell rings, the thrall can't be frightened or charmed.
--- Actions
***Grasping Hands.*** *Melee Weapon Attack:* +4 to hit, reach 5 ft., one target. *Hit:* 6 (1d8 + 2) bludgeoning damage, and the target is grappled (escape DC 12).
***Drag Under.*** The thrall swims up to its speed, pulling a creature it is grappling with it.
~~~

## Format 4: the 2024 5e layout

AC and initiative share a line; the score table gives each ability its score, modifier and saving throw; immunities are one line; the challenge line carries XP and proficiency bonus.

~~~ statblock
**Bog-Thrall**
*Medium Undead, Unaligned*
**AC** 9    **Initiative** −1 (9)
**HP** 26 (4d8 + 8)
**Speed** 25 ft., Swim 30 ft.
Str 14 +2 +2 | Dex 8 −1 −1 | Con 15 +2 +2
Int 3 −4 −4 | Wis 8 −1 +1 | Cha 5 −3 −3
**Immunities** Poison; Exhaustion, Poisoned
**Senses** Darkvision 60 ft.; Passive Perception 9
**Languages** Understands the languages it knew in life but can't speak
**CR** 1/2 (XP 100; PB +2)
**Traits**
***Peat-Preserved.*** The thrall drops to 1 Hit Point instead of 0 unless the damage is Fire or Radiant.
***Called by the Bell.*** While the abbey bell rings, the thrall can't have the Frightened or Charmed condition.
**Actions**
***Grasping Hands.*** *Melee Attack Roll:* +4, reach 5 ft. *Hit:* 6 (1d8 + 2) Bludgeoning damage, and the target has the Grappled condition (escape DC 12).
***Drag Under.*** The thrall swims up to its Speed, pulling a creature it is grappling with it.
~~~

## Format 5: the old-school one-line stat line

A different creature: old-school systems have no ability scores. The line splits into fields at each comma that comes before a known abbreviation, so the commas inside a value ("2 × claw (1d3), 1 × bite (1d3)") stay in it.

~~~ statblock name="Marsh Ghoul" meta="Undead, chaotic"
AC 6 [13], HD 2* (9hp), Att 2 × claw (1d3 + paralysis), 1 × bite (1d3), THAC0 18 [+1], MV 90' (30'), SV D12 W13 P14 B15 S16 (1), ML 9, AL Chaotic, XP 25, NA 1d6 (2d8), TT B
***Paralysis.*** A non-elf touched must save versus paralysis or be paralysed for 2d4 turns.
~~~

## Pasted with no fence: Homebrewery, both forms

The paste and import converter should find each of these and wrap it in a `~~~ statblock` fence. Nothing else in this file may be turned into a stat block.

{{monster,frame
## Bog-Thrall
*Medium undead, unaligned*
___
**Armor Class** :: 9
**Hit Points**  :: 26 (4d8 + 8)
**Speed**       :: 25 ft., swim 30 ft.
___
|  STR  |  DEX  |  CON  |  INT  |  WIS  |  CHA  |
|:-----:|:-----:|:-----:|:-----:|:-----:|:-----:|
|14 (+2)|8 (−1)|15 (+2)|3 (−4)|8 (−1)|5 (−3)|
___
**Challenge**            :: 1/2 (100 XP)
___
### Actions
***Drag Under.*** The thrall swims up to its speed, pulling a creature it is grappling with it.
}}

A paragraph between the two blocks, which must stay a paragraph.

___
> ## Bog-Thrall
>*Medium undead, unaligned*
> ___
> - **Armor Class** 9
>___
>|STR|DEX|CON|INT|WIS|CHA|
>|:---:|:---:|:---:|:---:|:---:|:---:|
>|14 (+2)|8 (−1)|15 (+2)|3 (−4)|8 (−1)|5 (−3)|
>___
> - **Challenge** 1/2 (100 XP)
> ### Actions
> ***Drag Under.*** The thrall swims up to its speed, pulling a creature it is grappling with it.

A closing paragraph, which must stay a paragraph too.
