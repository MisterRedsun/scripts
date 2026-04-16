"""
LaunchBox Export Script

PURPOSE:
    Exports game metadata, media (box art, screenshots, videos, etc.), and optionally 
    ROM files from LaunchBox to a Batocera-compatible folder structure with gamelist.xml files.
    Also exports to Mustard OS format with text descriptions and specific media formatting.

REQUIREMENTS:
    - Python 3.x
    - PIL/Pillow library (install via: pip install Pillow)
    - LaunchBox installation with game metadata and media
    - Sufficient disk space in the output directory

CONFIGURATION:
    Edit the variables below before running:
    - TEST_RUN: Set to True to simulate the export without copying files (for testing)
    - VERBOSE: Set to True to print detailed processing info for each game
    - LB_DIR: Path to your LaunchBox installation folder
    - LOCAL_OUTPUT_DIR: Where to export the files
    - OS_TARGETS: List of target operating systems to export. New OSes can be added by defining settings in OS_SETTINGS and adding to this list.
    - COPY_ROMS: Set True to copy ROM files (can be large!)
    - COPY_MEDIA: Set True to copy media files
    - CONVERT_TO_PNG: Convert JPG images to PNG format
    - RECENTS_ONLY: Export only recently added games
    - RECENT_DAYS: Number of days to consider "recent" if recents_only is True
    - USE_PLAYLIST: Set True to export only games in a specific playlist, with a prompt to choose from available playlists
    - PLATFORMS: A dictionary that maps LaunchBox platform names to output folder names
                 (uncomment the platforms you want to export)

FUNCTIONALITY:
    - Reads LaunchBox platform XML files to extract game metadata
    - Copies and organizes media files (box art, screenshots, marquees, videos, manuals)
    - Renames all media files to match ROM filenames for proper OS handling
    - Converts images to PNG format (optional) and trims marquee whitespace
    - Handles Batocera and Mustard OS export formats.
    - BATOCERA: Generates Batocera-compatible gamelist.xml files for each platform
    - MUSTARD OS: Generates a text file with descriptions for each game from LaunchBox metadata
    - Can filter to only export recently added games (recents_only mode)
      * When enabled, only exports games added within the last N days (configurable)
      * Useful for incremental updates without re-exporting your entire collection
      * Games without DateAdded metadata will be skipped in this mode
    - Preserves game ratings, release dates, developers, publishers, genres, and player counts
    - Export games from one or more LaunchBox playlists

OUTPUT STRUCTURE for Batocera:
    output_dir/
    ├── os_name/
    |   ├── playlist_name/           (if exporting from playlists, otherwise media goes directly under platform folder)
    |   |   ├── platform_name/
    │   │   │   ├── gamelist.xml
    │   │   │   ├── covers/          (box art)
    │   │   │   ├── screenshots/     (gameplay screenshots)
    │   │   │   ├── marquees/        (clear logos/wheels)
    │   │   │   ├── videos/          (video previews)
    │   │   │   └── manuals/         (PDF manuals)

OUTPUT STRUCTURE for Mustard OS:
    output_dir/
    ├── os_name/
    |   ├── playlist_name/           (if exporting from playlists, otherwise media goes directly under platform folder)
    |   |   ├── platform_name/
    │   │   │   ├── box/             (box art)
    │   │   │   ├── grid/            (icon for grid view)
    │   │   │   ├── preview/         (gameplay screenshots)
    │   │   │   ├── splash/          (splash screen to show before game starts)
    │   │   │   └── text/            (text files with game descriptions)

USAGE:
    1. Configure the variables in the "CONFIGURATION" section below
    2. Run the script: python launchbox-export.py
    3. Check the output directory for exported files
    4. Copy to SD card:
        * Batocera: Copy the platform folders to your Batocera system's roms directory
        * Mustard OS: Copy 

NOTES:
    - Image filenames are sanitized to handle special characters
    - All media files are renamed to match ROM filenames (e.g., if ROM is "game.chd", 
      box art becomes "game.png") to support platforms like ES-DE.
    - Marquee images are trimmed but not converted to preserve transparency
    - If media files cannot be found, warnings will be printed
    - Progress and statistics are displayed during execution
    - With recents_only=True, only games added in the last N days are exported
      (perfect for daily/weekly incremental exports to keep your collection updated)
    - Add option to export only games in a specific playlist, with a prompt to choose from available playlists.

TODO:
    - Export directly to SD card, verifying that it's loaded and has enough space before starting. Options: delete existing files
        before export, copy over existing files, or only copy over files that are missing from the SD card.
    - Add support for Garlic OS.
"""

from ast import If
import glob
import os
from datetime import datetime, timedelta
from shutil import copy
from typing import Any, Collection, Dict, List, Tuple, Optional
import xml.etree.ElementTree as ET
from xml.dom import minidom

try:
    from PIL import Image
except ImportError as e:
    raise SystemExit(
        "Pillow is required to run this script. Install it with: python -m pip install Pillow"
    ) from e


# ============================================================================
# CONFIGURATION
# ============================================================================

# Testing
TEST_RUN = False  # Set to True to go through the motions without copying files, but still generate
                  # output folder and gamelist.xml with correct paths for testing purposes.
VERBOSE = False    # Print detailed processing info for each game

# Export options
COPY_ROMS = True
COPY_MEDIA = True
CONVERT_TO_PNG = True
RECENTS_ONLY = False
RECENT_DAYS = 7  # Export games added in last N days
USE_PLAYLIST = True # Set to True to only export games in a specific playlist, or False to export all games in the platform
                    # Opens a prompt to choose an available playlist.

# Path to your LaunchBox folder
LB_DIR = r'C:\Users\<username>\LaunchBox'

# Where to put the top-level OS folders for the exported content on this PC
LOCAL_OUTPUT_DIR = r'C:\Users\<username>\Desktop'

# Strings for supported operating systems. Use these in OS_TARGETS and OS_SETTINGS.
BATOCERA = "Batocera"
MUSTARD_OS = "Mustard OS"

OS_TARGETS: list[str] = [
    # Comment out any OS to which you don't want to export
    #BATOCERA,
    MUSTARD_OS,
]

# Media types
SCREENSHOT = "screenshot"   # gameplay screen captures
MARQUEE = "marquee"         # game logos
BOX_ART = "box art"         # box covers)
MANUAL = "manual"           # PDF manuals
VIDEO = "video"             # video previews
ICON = "icon"               # grid view icon
SPLASH = "splash"           # game splash screen - plays before the game starts and should include title
DESCRIPTION = "description" # the game description that goes into a text file instead of XML (for Mustard OS)

# Subdirectories of Launchbox in which to search for each media type in order of preference.
LAUNCHBOX_SUBDIRS: Dict[str, Any] = {
    SCREENSHOT: ["Screenshot - Gameplay", 
                 "Screenshot", 
                 "Screenshot - Game Title", 
                 "Screenshot - Game Select", 
                 "Screenshot - High Scores", 
                 "Screenshot - Game Over"],
    MARQUEE:    ["Clear Logo"],
    BOX_ART:    ["Box - Front", 
                 "Front", 
                 "Box - Front - Reconstructed", 
                 "Box - Full"],
    MANUAL:     ["../manuals"],
    VIDEO:      ["../videos"],
    ICON:       ["Icon"],
    SPLASH:     ["Clear Logo",
                 "Banner",
                 "Fanart - Background",
                 "Fanart",
                 "Screenshot - Game Title",
                 "Screenshot"]
}

# Settings strings
GENERATE_XML = "generate_xml"
XML_PATH = "xml_path"
REQUIRED_OUTPUTS = "required_media"
MEDIA_TYPES = "media_types"
ROM_OUTPUT = "rom_output_folder"    # use to specify a subfolder for ROM output relative to the OS directory (or playlist directory if USE_PLAYLIST is True). 
                                    # If not specified, ROMs will be copied to the main output directory for that OS (or playlist).
PLAT = "<platform>"                 # this gets replaced with the platform name during export

OS_SETTINGS: Dict[str, Dict[str, Any]] = {
    BATOCERA: {
        GENERATE_XML: True,
        XML_PATH: PLAT + "/gamelist.xml",
        REQUIRED_OUTPUTS: ["covers", "screenshots", "marquees"], # Print errors if these output media are missing. Should match some values in the "output" field of MEDIA_TYPES.
        MEDIA_TYPES: [
            {"type": SCREENSHOT, "xmltag": "image", "output": PLAT + "/screenshots", "subdir": LAUNCHBOX_SUBDIRS[SCREENSHOT]},
            {"type": MARQUEE, "xmltag": "marquee", "output": PLAT + "/marquees", "subdir": LAUNCHBOX_SUBDIRS[MARQUEE], "saveas": "PNG"}, # convert marquees to PNG and trim whitespace to preserve transparency, which is required for proper display in Batocera
            {"type": BOX_ART, "xmltag": "thumbnail", "output": PLAT + "/covers", "subdir": LAUNCHBOX_SUBDIRS[BOX_ART]},
            {"type": MANUAL, "xmltag": "manual", "output": PLAT + "/manuals", "subdir": LAUNCHBOX_SUBDIRS[MANUAL]},
            {"type": VIDEO, "xmltag": "video", "output": PLAT + "/videos", "subdir": LAUNCHBOX_SUBDIRS[VIDEO]}
        ],
        ROM_OUTPUT: PLAT,
    },
    MUSTARD_OS: {
        GENERATE_XML: False,
        REQUIRED_OUTPUTS: ["box", "preview", "splash"], # technically, none of these are required, but it would be odd if LaunchBox didn't have these
        MEDIA_TYPES: [
            {"type": BOX_ART, "output": "MUOS/info/catalogue/" + PLAT + "/box", "subdir": LAUNCHBOX_SUBDIRS[BOX_ART], "saveas": "PNG", "width": 250, "height": 350},
            {"type": ICON, "output": "MUOS/info/catalogue/" + PLAT + "/grid", "subdir": LAUNCHBOX_SUBDIRS[ICON], "saveas": "PNG", "width": 120, "height": 120},
            {"type": SCREENSHOT, "output": "MUOS/info/catalogue/" + PLAT + "/preview", "subdir": LAUNCHBOX_SUBDIRS[SCREENSHOT], "saveas": "PNG", "width": 640, "height": 480},
            {"type": SPLASH, "output": "MUOS/info/catalogue/" + PLAT + "/splash", "subdir": LAUNCHBOX_SUBDIRS[SPLASH], "saveas": "PNG", "width": 640, "height": 480},
            {"type": DESCRIPTION, "output": "MUOS/info/catalogue/" + PLAT + "/text", "subdir": None}
        ],
        ROM_OUTPUT: "ROMS/" + PLAT,
    }
}

# Platforms: Launchbox name -> output folder name
PLATFORMS = {
    # Uncomment platforms you want to export:
    # "3DO Interactive Multiplayer": "3do",
    # "Arcade": "mame",
    # "Arcade - FBNeo": "fbneo",
    # "Atari 2600": "atari2600",
    # "Atari 7800": "atari7800",
    # "Atari Jaguar": "jaguar",
    # "Atari Lynx": "lynx",
    # "ColecoVision": "colecovision",
    # "Commodore 64": "c64",
    # "Commodore Amiga 500": "amiga500",
    # "Commodore Amiga 1200": "amiga1200",
    # "Commodore Amiga CD32": "amigacd32",
    # "Daphne": "daphne",
    # "GCE Vectrex": "vectrex",
    # "Mattel Intellivision": "intellivision",
    # "Magnavox Odyssey 2": "o2em",
    # "Microsoft MSX2": "msx2",
    # "Microsoft Xbox": "xbox",
    # "Moonlight": "moonlight",
    # "NEC TurboGrafx-16": "pcengine",
    # "NEC TurboGrafx-CD": "pcenginecd",
    # "Nintendo 3DS": "3ds",
    # "Nintendo 64": "n64",
    # "Nintendo DS": "nds",
    "Nintendo Entertainment System": "nes",
    # "Nintendo Famicom Disk System": "fds",
    # "Nintendo Game Boy Advance": "gba",
    # "Nintendo Game Boy Color": "gbc",
    "Nintendo Game Boy": "gb",
    # "Nintendo GameCube": "gamecube",
    # "Nintendo MSU-1": "snes-msu1",
    # "Nintendo Satellaview": "satellaview",
    # "Nintendo Switch": "switch",
    # "Nintendo Virtual Boy": "virtualboy",
    # "Nintendo Wii U": "wiiu",
    # "Nintendo Wii": "wii",
    # "Philips CD-i": "cdi",
    # "PICO-8": "pico8",
    # "Sammy Atomiswave": "atomiswave",
    # "Sega 32X": "sega32x",
    # "Sega CD": "segacd",
    # "Sega Dreamcast": "dreamcast",
    # "Sega Game Gear": "gamegear",
    # "Sega Genesis": "megadrive",
    # "Sega Master System": "mastersystem",
    # "Sega MSU-MD": "msu-md",
    # "Sega Model 3": "model3",
    # "Sega Naomi": "naomi",
    # "Sega Naomi 2": "naomi2",
    # "Sega Saturn": "saturn",
    # "Sega SG-1000": "sg1000",
    # "Sharp X68000": "x68000",
    # "Sinclair ZX Spectrum": "zxspectrum",
    # "SNK Neo Geo AES": "neogeo",
    # "SNK Neo Geo CD": "neogeocd",
    # "SNK Neo Geo Pocket Color": "ngpc",
    # "Sony Playstation": "psx",
    # "Sony Playstation 2": "ps2",
    # "Sony Playstation 3": "ps3",
    # "Sony Playstation Vita": "vita",
    # "Sony PSP": "psp",
    # "Super Nintendo Entertainment System": "snes",
    # "Windows": "steam",
    # "WonderSwan": "wswan",
    # "WonderSwan Color": "wswanc",
}

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

""" Wrapper functions to respect TEST_RUN mode for file operations"""

def _copy(src: str, dst: str, **kwargs) -> None:
    if TEST_RUN:
        print(f"    [TEST_RUN] Copy {src} -> {dst}")    # indented less since this isn't used for images
        return
    copy(src, dst, **kwargs)

def _save_image(img: Image.Image, output_path, **kwargs) -> None:
    if TEST_RUN:
        print(f"      [TEST_RUN] Save image to {output_path}")
        return
    img.save(output_path, **kwargs)

def _crop_image(img: Image.Image, name: str, bbox: tuple) -> Image.Image:
    if TEST_RUN:
        print(f"      [TEST_RUN] Crop {name} with bbox {bbox}")
        return img 
    return img.crop(bbox)

def _convert_image(img: Image.Image, name: str, fmt: str) -> Image.Image:
    if TEST_RUN:
        print(f"      [TEST_RUN] Convert {name} to {fmt}") 
        return img
    return img.convert(fmt)

def _resize_image(img: Image.Image, name: str, size: Tuple[int, int], resample: Image.Resampling = Image.Resampling.BICUBIC) -> Image.Image:
    if TEST_RUN:
        print(f"      [TEST_RUN] Resize {name} to {size}")
        return img
    if VERBOSE:
        print(f"      Resizing {name} from {img.size} to {size}")
    return img.resize(size, resample)

"""End of TEST_RUN wrappers"""

def sanitize_filename(filename: str) -> str:
    """Sanitize a filename by replacing invalid characters."""
    invalid_chars = [':', "'", '/', '*', '?', '"', '<', '>', '|']
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename


def find_media_file(game_name: str, media_files: List[str]) -> Optional[str]:
    """
    Find the first matching media file for a game.
    """
    sanitized_name = sanitize_filename(game_name)
    sanitized_lower = sanitized_name.lower()
    
    for filepath in media_files:
        filename = os.path.basename(filepath)
        filename_lower = filename.lower()
        
        # Check for common naming patterns
        if (filename.startswith(sanitized_name + "-0") or 
            filename.startswith(sanitized_name + ".") or
            filename_lower == sanitized_lower + ".mp4"):
            return filepath
    
    return None


def parse_date_added(date_str: str) -> Optional[datetime]:
    """Parse LaunchBox DateAdded field with error handling."""
    try:
        clean_date = date_str.strip().replace("Z", "")
        
        if "T" in clean_date:
            # Full datetime format
            return datetime.fromisoformat(clean_date.split(".")[0])
        else:
            # Date only format (YYYY-MM-DD)
            return datetime.fromisoformat(clean_date + "T00:00:00")
    except (ValueError, AttributeError):
        return None


def is_game_recent(game_element: ET.Element, cutoff_date: datetime) -> bool:
    """Check if a game was added after the cutoff date."""
    date_elem = game_element.find("DateAdded")
    
    if date_elem is None or not date_elem.text:
        return False
    
    added_date = parse_date_added(date_elem.text)
    return added_date is not None and added_date >= cutoff_date


def process_image(img_path: str, output_path: str, media_type: str, export_type: str = "", size: Optional[Tuple[int, int]] = None) -> None:
    """
    Process and save an image file with optional conversion and trimming.
    
    Args:
        img_path: Source image path
        output_path: Destination image path
        media_type: Type of media (marquee, screenshot, etc.)
        saveas: Output format for the image
        size: (width, height) for resizing if needed
    """
    img = Image.open(img_path)
    ext = os.path.splitext(img_path)[1].lower()
    name = os.path.basename(img_path) # for logging purposes

    # Resize image if size parameter is provided
    if size is not None:
        current_width, current_height = img.size
        aspect_ratio = current_width / current_height
        max_width, max_height = size

        # LaunchBox widths for box art is inconsistent, so first base width on height
        # Handling all image types for now, but maybe this needs to be for box art only?
        target_height = max_height
        target_width = int(max_height * aspect_ratio) 

        # And then resize to fit within the max_width.
        if target_width > max_width:
            target_width = max_width
            target_height = int(max_width / aspect_ratio)
        
        # Only resize if the current size is different from target size
        if (current_width, current_height) != (target_width, target_height):
            # Use LANCZOS resampling for high quality
            img = _resize_image(img, name, (target_width, target_height), Image.Resampling.LANCZOS)
    
    # Special handling for marquees: trim but don't convert
    if media_type == MARQUEE:
        bbox = img.getbbox()
        if bbox:
            img = _crop_image(img, name, bbox)
        _save_image(img, output_path, format="PNG")
        return

    # Convert to PNG if enabled and applicable
    if ext in [".jpg", ".jpeg", ".png"] and (CONVERT_TO_PNG or export_type == "PNG"):
        # Preserve transparency
        if 'A' in img.getbands():
            img = _convert_image(img, name, "RGBA")
        else:
            img = _convert_image(img, name, "RGB")
        _save_image(img, output_path, format="PNG")
    else:
        _save_image(img, output_path)

def save_media_file(
    source_path: str,
    output_dir: str,
    rom_basename: str,
    media_type: str,
    export_type: str = "",
    size: Optional[Tuple[int, int]] = None, # (width, height) for resizing if needed
) -> str:
    """
    Copy and process media file, returning relative path for XML.
    
    Args:
        source_path: Original media file path
        output_dir: Output directory for this media type
        rom_basename: Base name of the ROM (without extension)
        media_type: Type of media for special handling
    
    Returns:
        Relative path string for use in gamelist.xml
    """
    os.makedirs(output_dir, exist_ok=True)
    ext = os.path.splitext(source_path)[1].lower()

    if VERBOSE:
        print(f"    Processing {media_type}: {source_path}")
    
    # Determine output filename and extension
    if ext in [".jpg", ".jpeg", ".png"] and (CONVERT_TO_PNG or export_type == "PNG"):
        new_filename = f"{rom_basename}.png"
    else:
        new_filename = f"{rom_basename}{ext}"
    
    output_path = os.path.join(output_dir, new_filename)
    
    try:
        # Process images, copy other media types
        if ext in [".jpg", ".jpeg", ".png"]:
            process_image(source_path, output_path, media_type, export_type, size)
        elif COPY_MEDIA:
            _copy(source_path, output_path)
    except Exception as e:
        print(f"  Warning: Failed to process {source_path}: {e}")
        # Attempt fallback copy
        try:
            if COPY_MEDIA:
                _copy(source_path, output_path)
        except Exception as e2:
            print(f"  Error: Fallback copy also failed: {e2}")
    
    # Return relative path for XML
    return f"./{os.path.basename(output_dir)}/{new_filename}"


def build_media_index(media_dir: str) -> List[str]:
    """Build a list of all media files in a directory."""
    if not os.path.isdir(media_dir):
        return []
    
    return [
        f for f in glob.glob(os.path.join(media_dir, "**"), recursive=True)
        if os.path.isfile(f)
    ]


def extract_game_metadata(game_elem: ET.Element) -> Dict[str, str]:
    """Extract all metadata fields from a game XML element."""
    metadata = {}
    
    # Star rating (convert to 0-1 scale)
    if (rating_elem := game_elem.find("StarRating")) is not None and rating_elem.text:
        try:
            rating_value = int(rating_elem.text)
            metadata["rating"] = str(rating_value * 2 / 10)
        except ValueError:
            pass
    
    # Release date (convert to Batocera format)
    if (release_elem := game_elem.find("ReleaseDate")) is not None and release_elem.text:
        metadata["releasedate"] = release_elem.text.replace("-", "").split("T")[0] + "T000000"
    
    # Simple text fields
    text_fields = ["Developer", "Publisher", "Genre", "Notes"]
    xml_to_key = {
        "Developer": "developer",
        "Publisher": "publisher",
        "Genre": "genre",
        "Notes": "desc"
    }
    
    for xml_tag in text_fields:
        if (elem := game_elem.find(xml_tag)) is not None and elem.text:
            metadata[xml_to_key[xml_tag]] = elem.text
    
    # Max players (handle "0" prefix)
    if (players_elem := game_elem.find("MaxPlayers")) is not None and players_elem.text:
        mp = players_elem.text
        metadata["players"] = "1+" if mp.startswith("0") else mp
    
    return metadata


def write_gamelist_xml(games: List[Dict[str, str]], output_path: str) -> None:
    """Write games list to Batocera-compatible XML file."""
    root = ET.Element("gameList")
    
    for game_data in games:
        game_elem = ET.SubElement(root, "game")
        for key, value in game_data.items():
            child = ET.SubElement(game_elem, key)
            child.text = value
    
    # Pretty print XML
    xml_str = minidom.parseString(ET.tostring(root)).toprettyxml(indent="    ")
    
    # Remove XML declaration
    xml_lines = xml_str.splitlines()
    if xml_lines[0].startswith("<?xml"):
        xml_str = "\n".join(xml_lines[1:])
    
    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml_str)


def write_description_file(descriptions: Dict[str, str], output_dir: str, rom_basename: str) -> str:
    """Write game description to a text file and return relative path."""
    os.makedirs(output_dir, exist_ok=True)
    filename = f"{rom_basename}.txt"
    output_path = os.path.join(output_dir, filename)
    
    if TEST_RUN:
        print(f"    [TEST_RUN] Write description to {output_path}")
        return f"./{os.path.basename(output_dir)}/{filename}"
    
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            for key in ["name", "developer", "publisher", "genre", "releasedate", "players", "rating", "desc"]:
                if key in descriptions:
                    if key is "desc":
                        f.write(f"\nDescription:\n{descriptions[key]}\n")
                        continue
                    if key is "releasedate":
                        # Reformat release date for readability
                        try:
                            dt = datetime.strptime(descriptions[key], "%Y%m%dT%H%M%S")
                            f.write(f"Release Date: {dt.strftime("%B %d, %Y")}\n")
                        except ValueError:
                            pass
                        continue
                    f.write(f"{key.capitalize()}: {descriptions[key]}\n")
    except Exception as e:
        print(f"    Warning: Failed to write description file: {e}")
    
    return f"./{os.path.basename(output_dir)}/{filename}"


def get_playlist_game_ids(playlist_name: str) -> set:
    """Returns a set of Game IDs found in the specified playlist XML."""
    playlist_path = os.path.join(LB_DIR, 'Data', 'Playlists', f'{playlist_name}.xml')
    ids = set()
    
    if not os.path.exists(playlist_path):
        print(f"--- Playlist {playlist_name} not found at {playlist_path} ---")
        return ids

    try:
        tree = ET.parse(playlist_path)
        root = tree.getroot()
        for game in root.findall('PlaylistGame'):
            game_id = game.find('GameId')
            if game_id is not None:
                ids.add(game_id.text)
    except Exception as e:
        print(f"Error parsing playlist: {e}")
        
    return ids


def choose_playlist() -> Optional[list[str]]:
    """Prompts the user to choose a playlist from the available playlists."""
    playlists_dir = os.path.join(LB_DIR, 'Data', 'Playlists')
    
    if not os.path.isdir(playlists_dir):
        print(f"Error: Playlists directory not found at {playlists_dir}")
        return None
    
    playlist_files = [f for f in os.listdir(playlists_dir) if f.endswith('.xml')]
    
    if not playlist_files:
        print("No playlists found in LaunchBox.")
        return None
    
    print("\nAvailable Playlists:")
    for idx, filename in enumerate(playlist_files, start=1):
        print(f"{idx}. {os.path.splitext(filename)[0]}")
    
    while True:
        choice = input("Enter the number(s) of the playlist(s) to export separated by a space (or 'q' to quit): ")
        
        if choice.lower() == 'q':
            return None
        
        try:
            idxs = [int(x) - 1 for x in choice.split()]
            if all(0 <= idx < len(playlist_files) for idx in idxs):
                return [os.path.splitext(playlist_files[idx])[0] for idx in idxs]
            else:
                print("Invalid selection. Please try again.")
        except ValueError:
            print("Please enter a valid number or 'q' to quit.")


# ============================================================================
# MAIN PROCESSING
# ============================================================================

def process_platform(
    target_os: str,
    platform_lb: str,
    platform_rp: str,
    output_dir: str,
    cutoff_date: Optional[datetime],
    playlist_game_ids: Optional[Collection[str]] = None,
) -> tuple:
    """
    Process a single platform and return statistics.

    target_os must be verified to be in OS_MAPPINGS before calling this function.
    
    Returns:
        Tuple of (games_exported, media_copied)
    """
    print(f"\nProcessing {platform_lb} → {platform_rp}")
    
# TODO: Need to properly handle media types' output directories that use <platform> placeholder

    # Build paths
    lb_platform_xml = os.path.join(LB_DIR, "Data", "Platforms", f"{platform_lb}.xml")
    rom_output_relpath = OS_SETTINGS[target_os].get(ROM_OUTPUT, "").replace(PLAT, platform_rp)
    rom_output_dir = os.path.join(output_dir, rom_output_relpath) if rom_output_relpath else output_dir
    
    # Check if platform XML exists
    if not os.path.isfile(lb_platform_xml):
        print(f"  Warning: Platform XML not found: {lb_platform_xml}")
        return 0, 0
    
    # Parse XML
    try:
        xmltree = ET.parse(lb_platform_xml)
    except ET.ParseError as e:
        print(f"  Error: Failed to parse XML: {e}")
        return 0, 0
    
    # Build media file indexes
    print("  Indexing media files...")
    media_types = OS_SETTINGS[target_os][MEDIA_TYPES]
    for media in media_types:
        # Collect files from all possible subdirectories for this media type (although only the first match will be used)
        all_files = []
        if media["type"] == DESCRIPTION:
            # Descriptions don't have files, but we want to keep the structure consistent
            media["files"] = []
            continue
        for sub in media["subdir"]:
            if sub.startswith(".."):
                media_dir = os.path.join(LB_DIR, sub.replace("..", "").strip("/\\"), platform_lb)
            else:
                media_dir = os.path.join(LB_DIR, "images", platform_lb, sub)
            all_files.extend(build_media_index(media_dir))  # Collect from all dirs
        media["files"] = all_files  # Store combined list for later use
    
    # Create output directories
    os.makedirs(rom_output_dir, exist_ok=True)

    # Process games
    games_found = []
    total_games = 0
    local_media_count = 0
    generating_xml = OS_SETTINGS[target_os][GENERATE_XML]
    
    for game in xmltree.getroot().iter("Game"):
        total_games += 1

        try:
            # Check if game is recent enough
            if cutoff_date and not is_game_recent(game, cutoff_date):
                continue
            
            # Extract ROM info
            rom_path_elem = game.find("ApplicationPath")
            title_elem = game.find("Title")
            
            if rom_path_elem is None or title_elem is None:
                continue
            
            id_elem = game.find("ID")
            id_text = id_elem.text if id_elem is not None else None

            if playlist_game_ids is not None:
                if not id_text or id_text not in playlist_game_ids:
                    continue

            rom_path = rom_path_elem.text or ""
            if not rom_path:
                continue

            rom_name = os.path.basename(rom_path)
            rom_basename = os.path.splitext(rom_name)[0]

            game_title = title_elem.text or ""
            if not game_title:
                continue
            
            print(f"  Processing game: {game_title}")

            # Build game data
            game_data = {
                "path": f"./{rom_name}",
                "name": game_title
            }
            
            # Add metadata
            game_data.update(extract_game_metadata(game))
            
            # Process media files
            sanitized_title = sanitize_filename(game_title)
            media_types = OS_SETTINGS[target_os][MEDIA_TYPES]
            required_media = OS_SETTINGS[target_os][REQUIRED_OUTPUTS]

            for media in media_types:
                media_output_temp = media["output"].replace(PLAT, platform_rp)
                media_output_dir = os.path.join(output_dir, media_output_temp)

                if media ["type"] == DESCRIPTION:
                    write_description_file(game_data, media_output_dir, rom_basename)
                    continue

                media_path = find_media_file(sanitized_title, media["files"])
                
                if media_path:
                    export_type = media.get("saveas", "")
                    wh = (media.get("width"), media.get("height"))
                    rel_path = save_media_file(media_path, media_output_dir, rom_basename, media["type"], export_type, wh)
                    if generating_xml:
                        game_data[media["xmltag"]] = rel_path
                    local_media_count += 1
                else:
                    if generating_xml:
                        game_data[media["xmltag"]] = ""
                    # Only print errors for essential media types (covers, screenshots, marquees)
                    if media["output"] in required_media:
                        print(f"    [ERROR]: No {media['type']} found for: {game_title}")
            
            # Copy ROM if enabled
            if COPY_ROMS and os.path.isfile(rom_path):
                try:
                    _copy(rom_path, rom_output_dir)
                except Exception as e:
                    print(f"  Warning: Failed to copy ROM {rom_name}: {e}")
            
            games_found.append(game_data)
            
        except Exception as e:
            print(f"  Error processing game: {e}")
            continue
    
    # Write gamelist.xml
    
    if generating_xml and games_found:
        xml_relpath = OS_SETTINGS[target_os][XML_PATH].replace(PLAT, platform_rp)
        xml_path = os.path.join(output_dir, xml_relpath)
        try:
            write_gamelist_xml(games_found, xml_path)
        except Exception as e:
            print(f"  Error writing gamelist.xml: {e}")
            return 0, 0
    
    # Print summary
    if RECENTS_ONLY:
        print(f"  Exported {len(games_found)} recent games out of {total_games} total")
    else:
        print(f"  Exported {len(games_found)} games")
    
    return len(games_found), local_media_count

def main():
    """Main execution function."""
    print("=" * 70)
    print("LaunchBox to Device Export")
    print("=" * 70)
    
    # Calculate cutoff date for recent games
    cutoff_date = None
    if RECENTS_ONLY:
        cutoff_date = datetime.now() - timedelta(days=RECENT_DAYS)
        print(f"\nExporting games added since: {cutoff_date.strftime('%Y-%m-%d')}")

    playlists = {}
    playlist_names = None

    if USE_PLAYLIST:
        # call function to get game ids in all selected playlists, then filter platforms to only include those games
        playlist_names = choose_playlist()
        skipped_playlist_count = 0

        if not playlist_names:
            print("No playlist selected. Exiting.")
            return
        
        for playlist_name in playlist_names:
            game_ids = get_playlist_game_ids(playlist_name)
            if not game_ids:
                skipped_playlist_count += 1
                print(f"No games found in playlist '{playlist_name}'. Skipping.")
                continue
            playlists[playlist_name] = game_ids

        if skipped_playlist_count == len(playlist_names):
            print(f"No games found in any of the selected playlists. Exiting.")
            return
    
    for target_os in OS_TARGETS:
        print(f"\n--- Exporting for {target_os} ---")

        if target_os not in OS_SETTINGS:
            continue

        output_dir_base = os.path.join(LOCAL_OUTPUT_DIR, target_os)

        # Determine what to process: playlists or a single run
        if USE_PLAYLIST:
            items_to_process = playlists.items()
        else:
            items_to_process = [(None, None)]

        for playlist_name, game_ids in items_to_process:
            if playlist_name:
                output_dir = os.path.join(output_dir_base, playlist_name)
                game_count = game_ids and len(game_ids) or 0
                print(f"\nExporting games from playlist: {playlist_name} ({game_count} games)")
            else:
                output_dir = output_dir_base
                print(f"\nExporting all games")

            # Process each platform
            total_games = 0
            total_media = 0
            total_platforms = 0

            for platform_lb, platform_rp in PLATFORMS.items():
                games_count, media_count = process_platform(target_os, platform_lb, platform_rp, output_dir, cutoff_date, game_ids if USE_PLAYLIST else None)
                
                if games_count > 0:
                    total_games += games_count
                    total_media += media_count
                    total_platforms += 1
            
            # Print summary for this export
            print("\n" + "=" * 70)
            if playlist_name:
                print(f"  Playlist '{playlist_name}' Export Complete!")
            else:
                print(f"  Export Complete!")
            print(f"  Platforms: {total_platforms}")
            print(f"  Games: {total_games}")
            print(f"  Media files: {total_media}")
            print("=" * 70)
            print("")


if __name__ == "__main__":
    main()
