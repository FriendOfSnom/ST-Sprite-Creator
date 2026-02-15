# AI Sprite Creator

AI-powered character sprite generator for visual novels, using Google Gemini. Create complete characters with multiple outfits, expressions, and automatic background removal in a guided wizard.

---

## Features

- **Three creation modes**: Reference image, text prompt, or character fusion
- **Multiple outfits**: Casual, formal, athletic, swimsuit, uniform (custom too)
- **Expression generation**: Neutral, happy, sad, angry, surprised, and custom expressions
- **Automatic background removal** with manual touch-up tools
- **Add to existing characters**: Add new outfits or expressions to previously created characters
- **Scale comparison** with 77 reference sprites for accurate in-game sizing
- **Expression sheet generation** for visual reference
- **Sprite Tester** to preview characters in a simulated Ren'Py environment

---

## Getting Started

### API Key Setup

This tool requires a Google Cloud API key with Gemini access.

1. Go to [Google AI Studio](https://aistudio.google.com)
2. Create a project and enable the Gemini API
3. Generate an API key
4. Enter it in the **API Settings** dialog on the launcher

New Google Cloud accounts get **$300 in free credits** - more than enough for hundreds of characters.

### Running the App

**From executable (recommended):**
Double-click `sprite_creator.exe`

**From source:**

```bash
pip install -r requirements.txt
python -m sprite_creator
```

---

## Launcher Modes

### Character Sprite Creator (Recommended)

The full character creation wizard. Walks you through every step:

1. **Source Selection** - Upload an image, describe a character, or fuse two together
2. **Character Setup** - Set name, voice, archetype; crop and normalize the base image
3. **Generation Options** - Pick outfits and expressions to generate
4. **Review** - Confirm selections before generation begins
5. **Outfit Review** - Review generated outfits, adjust background removal, regenerate
6. **Expression Review** - Review expressions, touch up backgrounds
7. **Eye Line & Color** - Set eye position and pick name color
8. **Scale** - Compare with reference sprites for in-game sizing
9. **Complete** - View summary and open character folder

### Add to Character

Add new outfits or expressions to an existing character folder:

- Select a base sprite from the character's existing images
- Normalize it to match AI output resolution
- Generate new outfits that match the existing character's style
- New outfits become new pose letters (c, d, e...)
- Existing settings (voice, name, eye line) are preserved

### Expression Sheet Generator

Create expression reference sheet images from existing character folders. Useful for visual reference or sharing character designs.

### Sprite Tester

Preview character sprites in a simulated Ren'Py environment. Test outfit switching, expression changes, and the character loading system.

---

## Output Structure

```
character_name/
  character.yml             Metadata (voice, scale, eye line, colors)
  How-To-Use.txt            Instructions for using with Student Transfer
  base.png                  Original base image for reference
  a/                        Pose A (first outfit)
    outfits/
      0.png                 Outfit image
    faces/face/
      0.png                 Neutral expression
      1.png                 Happy
      2.png                 Sad
      ...                   Additional expressions
  b/                        Pose B (second outfit)
    ...
  expression_sheets/        Generated reference sheets
```

Characters are compatible with Student Transfer's character system and any Ren'Py project that uses the same folder structure.

---

## Backup System

Full-size character images are automatically backed up before scaling. These backups are stored in `~/.sprite_creator/backups/` and provide the highest quality source images when adding new content to existing characters.

Use the **Clear Backups** button on the launcher to free disk space. Note that clearing backups means "Add to Character" will use the scaled (slightly lower quality) images from the character folder instead.

---

## Tips

- Every wizard step has a **?** help button with detailed instructions
- Use the **ST Style** toggle to match Student Transfer art style, or disable it for any art style
- If Gemini's safety filters block a generation, the wizard skips it and continues
- You can regenerate individual outfits and expressions without starting over
- **View API Usage** on the launcher opens Google AI Studio's usage dashboard

---

## Troubleshooting

### API key not working

- Make sure you're using a Google Cloud API key (not a basic AI Studio free-tier key)
- Check your key in **API Settings** on the launcher
- Verify your account has credits at [AI Studio Usage](https://aistudio.google.com/usage)

### Outfit or expression generation blocked

- Gemini's safety filters may block certain content
- The wizard skips blocked items and continues with others
- Try regenerating with a different random seed
- Custom prompts are more likely to be blocked than random ones

### Background removal looks wrong

- Adjust **Tolerance** slider (higher = more aggressive removal)
- Adjust **Depth** slider (higher = cleaner edges)
- Switch to **Manual** mode for click-based flood fill
- Use **Touch Up BG** on expression review for fine adjustments

### Next button is disabled

- **Character Setup**: Fill in Voice, Name, and Archetype, then accept your selection
- **Add to Character**: Normalize and accept the base sprite first
- **Review**: Check the acknowledgment box if a warning is shown
- **Expression Review**: Navigate through all outfits before continuing

### Log files

- Logs are saved to `logs/sprite_creator.log` next to the executable
- The log file resets on each launch
- Include log contents when reporting bugs

---

## Requirements

- **Python 3.10+** (when running from source)
- **Google Gemini API Key** (Google Cloud with credits)
- **Windows 10/11** (primary platform; macOS/Linux may work from source)

### Dependencies (installed via requirements.txt)

- google-generativeai
- Pillow (PIL)
- PyYAML
- rembg + onnxruntime (background removal)
- requests, beautifulsoup4

---

## License

This software is provided as-is for educational and personal use.

---

_AI-powered character sprite generation for visual novels_
