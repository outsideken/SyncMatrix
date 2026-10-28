# Legacy matplotlib Sync Matrix

The original notebook, its `Config_*.json` files and the PNGs it produced, kept
for reference. **The d3 version does not use anything in this folder**: its
matrices are defined in [`../config/`](../config/README.md).

The notebook still runs from this folder (it reads and writes the
`Config_*.json` files next to it). Those files use the old matplotlib-shaped
format (axis/line styling, slot-based banners, bottom-up row lists,
`{colour: [keys]}` colour map) and are no longer kept in step with
`config/`.
