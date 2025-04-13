# -*- coding: utf-8 -*-
"""
by @ATC1441 ATCnetz.de 
Displays a word clock on an OpenEPaperLink E-Paper display.
Retrieves the current time, determines which words to highlight,
generates an image, and sends it to the display via the OEP Link AP.
"""

import time
import datetime
from PIL import Image, ImageDraw, ImageFont
import os
import requests
import io
import sys  # Required for exit()
import re # For sanitizing filenames

# --- Global Configuration ---
DISPLAY_WIDTH = 960
DISPLAY_HEIGHT = 672
COLOR_BACKGROUND = (255, 255, 255)  # White
COLOR_INACTIVE_TEXT = (0, 0, 0)     # Black
COLOR_ACTIVE_TEXT = (255, 0, 0)     # Red (or your desired highlight color)

# --- IMPORTANT: Server Configuration ---
# Adjust these values to match your OpenEPaperLink setup
# Find these in your OpenEPaperLink Access Point logs or configuration
TARGET_MAC = "E9CE0B3347320241"  # <--- !!! SET YOUR DISPLAY'S MAC ADDRESS HERE !!!
AP_IP = "192.168.1.76"           # <--- !!! SET YOUR OPENEPAPERLINK AP's IP ADDRESS HERE !!!
DITHER = 0                       # Dithering flag for the server (0=off, 1=on). Affects image processing on the AP.

# --- Font & Size Configuration ---
INACTIVE_FONT_SIZE_RATIO = 0.7  # Ratio of inactive font size relative to active font size
MIN_INACTIVE_FONT_SIZE = 10     # Minimum pixel size for the inactive font
FONT_PATH = None                # Will be dynamically searched for below

# --- Time Check Interval ---
CHECK_INTERVAL_SECONDS = 50     # How often to check if the minute has changed

# =============================================================================
# ENGLISH LANGUAGE DEFINITIONS (Layout, Positions, Logic)
# =============================================================================

# ** Grid Layout (11 columns x 10 rows) **
GRID_LAYOUT = [
    "ITLISMTENSA", # 0 IT L IS M TEN S A
    "HALFQUARTER", # 1 HALF QUARTER
    "TWENTYFIVES", # 2 TWENTY FIVE S
    "MINUTESPAST", # 3 MINUTES PAST
    "TOXONELEVEN", # 4 TO X ONE ELEVEN
    "TWOSIXTHREE", # 5 TWO SIX THREE
    "FOURFIVESEV", # 6 FOUR FIVE SEVEN (Abbreviated)
    "EIGHTNINEAM", # 7 EIGHT NINE AM
    "PMTWELVEXTN", # 8 PM TWELVE X TEN (Filler)
    "OCLOCKYTIME"  # 9 OCLOCK Y TIME (Filler)
]

# ** Word positions matching GRID_LAYOUT **
# Maps internal keys to coordinates: [(row, start_col, end_col)]
# end_col is inclusive.
WORD_POSITIONS = {
    # Core words
    "IT": [(0, 0, 1)],
    "IS": [(0, 3, 4)],
    "A": [(0, 10, 10)],
    "MINUTES": [(3, 0, 6)],
    "PAST": [(3, 7, 10)],
    "TO": [(4, 0, 1)],
    "OCLOCK": [(9, 0, 5)],

    # Minute words
    "QUARTER": [(1, 4, 10)],
    "TWENTY": [(2, 0, 5)],
    "FIVE_M": [(2, 6, 9)],   # "FIVE" for minutes
    "HALF": [(1, 0, 3)],
    "TEN_M": [(0, 6, 8)],    # "TEN" for minutes

    # Hour words
    "ONE_H": [(4, 3, 5)],
    "TWO_H": [(5, 0, 2)],
    "THREE_H": [(5, 6, 10)],
    "FOUR_H": [(6, 0, 3)],
    "FIVE_H": [(6, 4, 7)],   # "FIVE" for hours
    "SIX_H": [(5, 3, 5)],
    "SEVEN_H": [(6, 8, 10)], # "SEV"
    "EIGHT_H": [(7, 0, 4)],
    "NINE_H": [(7, 5, 8)],
    "TEN_H": [(0, 6, 8)],    # "TEN" for hours (shares with TEN_M)
    "ELEVEN_H": [(4, 5, 10)],
    "TWELVE_H": [(8, 2, 7)],

    # AM/PM (Optional - currently not used in get_active_words logic)
    # "AM": [(7, 9, 10)],
    # "PM": [(8, 0, 1)],
}

# Maps hour number (1-12) to the internal hour keys
HOUR_WORDS = {
    1: "ONE_H", 2: "TWO_H", 3: "THREE_H", 4: "FOUR_H", 5: "FIVE_H", 6: "SIX_H",
    7: "SEVEN_H", 8: "EIGHT_H", 9: "NINE_H", 10: "TEN_H", 11: "ELEVEN_H", 12: "TWELVE_H"
}

# Maps internal keys to their exact string representation in the grid
# Used for layout verification.
INTERNAL_KEY_TO_WORD = {
    "IT": "IT", "IS": "IS", "A": "A", "QUARTER": "QUARTER", "TWENTY": "TWENTY",
    "FIVE_M": "FIVE", "HALF": "HALF", "TEN_M": "TEN", "MINUTES": "MINUTES",
    "PAST": "PAST", "TO": "TO", "OCLOCK": "OCLOCK",
    "ONE_H": "ONE", "TWO_H": "TWO", "THREE_H": "THREE", "FOUR_H": "FOUR",
    "FIVE_H": "FIVE", "SIX_H": "SIX", "SEVEN_H": "SEV", "EIGHT_H": "EIGHT",
    "NINE_H": "NINE", "TEN_H": "TEN", "ELEVEN_H": "ELEVEN", "TWELVE_H": "TWELVE",
    # "AM": "AM", "PM": "PM" # Add if using AM/PM
}

# =============================================================================
# TIME LOGIC FUNCTION
# =============================================================================

def get_active_words(hour, minute, hour_words_map):
    """
    Calculates the list of internal keys for words that should be active
    based on the provided hour and minute.
    """
    active_keys = ["IT", "IS"]
    display_hour = hour % 12
    if display_hour == 0:
        display_hour = 12  # 0 hour is 12 AM/PM

    # Use precise minute for logic, rounding might happen implicitly by minute ranges
    minute_precise = minute

    # Determine the hour word to display (current or next)
    current_hour_key = hour_words_map.get(display_hour)
    next_hour = (display_hour % 12) + 1 # Calculate next hour (1-12)
    next_hour_key = hour_words_map.get(next_hour)

    # Determine if "MINUTES" word should be shown based on common word clock patterns
    # Typically shown for 5, 10, 20, 25 mins past/to. Not for quarter, half, o'clock.
    show_minutes_word = minute_precise in range(5, 15) or \
                        minute_precise in range(20, 30) or \
                        minute_precise in range(35, 45) or \
                        minute_precise in range(50, 60)

    temp_keys = [] # Use a temporary list for minute/hour/past/to logic

    # --- Time Logic (Minute intervals) ---
    if minute_precise < 5:            # O'Clock
        temp_keys.extend([current_hour_key, "OCLOCK"])
    elif minute_precise < 10:         # Five Past
        temp_keys.append("FIVE_M")
    elif minute_precise < 15:         # Ten Past
        temp_keys.append("TEN_M")
    elif minute_precise < 20:         # Quarter Past
        temp_keys.extend(["A", "QUARTER"])
    elif minute_precise < 25:         # Twenty Past
        temp_keys.append("TWENTY")
    elif minute_precise < 30:         # Twenty Five Past
        temp_keys.extend(["TWENTY", "FIVE_M"])
    elif minute_precise < 35:         # Half Past
        temp_keys.append("HALF")
    # --- Switch to "TO" logic after half past ---
    elif minute_precise < 40:         # Twenty Five To
        temp_keys.extend(["TWENTY", "FIVE_M"])
    elif minute_precise < 45:         # Twenty To
        temp_keys.append("TWENTY")
    elif minute_precise < 50:         # Quarter To
        temp_keys.extend(["A", "QUARTER"])
    elif minute_precise < 55:         # Ten To
        temp_keys.append("TEN_M")
    else: # minute_precise >= 55       # Five To
        temp_keys.append("FIVE_M")

    # Add "MINUTES" word if applicable (and not o'clock/quarter/half)
    if show_minutes_word:
        temp_keys.append("MINUTES")

    # Add "PAST" or "TO" (except for O'Clock and Half Past)
    if 0 < minute_precise < 35:
        # Add "PAST" unless it's exactly half past (handled by "HALF" key alone)
        if minute_precise not in range(30, 35) and minute_precise not in range(0, 5):
            temp_keys.append("PAST")
    elif minute_precise >= 35:
        temp_keys.append("TO")

    # Add the correct Hour word
    if 0 < minute_precise < 35:
        temp_keys.append(current_hour_key) # Hour relevant to "PAST"
    elif minute_precise >= 35:
        temp_keys.append(next_hour_key)    # Hour relevant to "TO"
    # Note: O'Clock hour is added in the first 'if' condition

    # Filter out any None keys (if hour lookup failed) and add to main list
    active_keys.extend([key for key in temp_keys if key is not None])

    # Example: Add AM/PM if desired (needs grid space and WORD_POSITIONS entries)
    # if hour < 12:
    #     active_keys.append("AM") # Make sure "AM" is in WORD_POSITIONS
    # else:
    #     active_keys.append("PM") # Make sure "PM" is in WORD_POSITIONS

    return active_keys


# =============================================================================
# LAYOUT VERIFICATION FUNCTION
# =============================================================================

def verify_layout(grid, word_map, key_to_word_map):
    """
    Checks if the letters at positions defined in word_map match the
    expected words defined in key_to_word_map, based on the grid layout.
    Returns True if verification passes, False otherwise.
    """
    print("Verifying layout definition...")
    all_ok = True
    checked_keys = set() # To avoid checking shared words multiple times if needed

    # Basic Grid Structure Check
    if not grid or not isinstance(grid, list) or not grid[0] or not isinstance(grid[0], str):
        print("ERROR: Grid layout is invalid or empty.")
        return False
    grid_rows = len(grid)
    grid_cols = len(grid[0])
    for r, row_str in enumerate(grid):
        if not isinstance(row_str, str) or len(row_str) != grid_cols:
            print(f"ERROR: Grid row {r} is invalid or has wrong length ({len(row_str)}), expected {grid_cols}.")
            return False
    print(f"Grid dimensions: {grid_rows} rows x {grid_cols} columns.")

    # Word Map Verification Loop
    for key, positions in word_map.items():
        if key in checked_keys:
            continue
        checked_keys.add(key)

        if not positions:
            # It's okay for a key to exist but have no positions if it's not used
            if key in key_to_word_map:
                 print(f"INFO: Key '{key}' has no positions defined (Expected word: {key_to_word_map.get(key, '???')}).")
            continue # Skip keys with no positions

        if key not in key_to_word_map:
            print(f"WARNING: Key '{key}' exists in WORD_POSITIONS but not in INTERNAL_KEY_TO_WORD verification map. Cannot verify.")
            continue # Cannot verify this key

        expected_word = key_to_word_map[key]
        extracted_word = ""
        valid_positions_found = True

        # Ensure positions is always iterable (list of tuples)
        pos_list = positions if isinstance(positions, list) else [positions]

        for pos_info in pos_list:
            if isinstance(pos_info, (list, tuple)) and len(pos_info) == 3:
                row, start_col, end_col = pos_info
                # Check coordinate bounds carefully
                if 0 <= row < grid_rows and \
                   0 <= start_col < grid_cols and \
                   0 <= end_col < grid_cols and \
                   start_col <= end_col:
                    try:
                        # Python slicing: end index is exclusive, so add 1
                        extracted_segment = grid[row][start_col : end_col + 1]
                        extracted_word += extracted_segment
                        # Optional: Add detailed debug print here if needed
                        # print(f"DEBUG: Check Key:'{key}' Pos:{pos_info} -> GridRow:{row}='{grid[row]}' -> Extracted: '{extracted_segment}'")
                    except IndexError:
                        print(f"ERROR: IndexError accessing grid slice [{start_col}:{end_col + 1}] for key '{key}' on row {row}.")
                        all_ok = False
                        valid_positions_found = False
                        break # Stop checking this key
                else:
                    print(f"ERROR: Invalid coordinates {pos_info} for key '{key}' (Expected: '{expected_word}'). Out of grid bounds ({grid_rows}x{grid_cols}).")
                    all_ok = False
                    valid_positions_found = False
                    break # Stop checking this key
            else:
                print(f"ERROR: Malformed position info '{pos_info}' for key '{key}' (Expected: '{expected_word}'). Should be (row, start_col, end_col).")
                all_ok = False
                valid_positions_found = False
                break # Stop checking this key

        if not valid_positions_found:
            continue # Move to the next key if errors occurred for this one

        # Compare the fully extracted word (potentially from multiple segments)
        if extracted_word != expected_word:
            print(f"ERROR: Mismatch for key '{key}'. Expected '{expected_word}', but positions {positions} map to '{extracted_word}' in the grid.")
            all_ok = False

    if all_ok:
        print("Layout verification successful. WORD_POSITIONS match GRID_LAYOUT and INTERNAL_KEY_TO_WORD.")
    else:
        print("--- LAYOUT VERIFICATION FAILED. Please check ERROR messages above and correct GRID_LAYOUT or WORD_POSITIONS. ---")

    return all_ok

# =============================================================================
# UTILITY FUNCTIONS (Font Finding, Drawing, Sending)
# =============================================================================

def find_font():
    """
    Tries to find a suitable TTF font file on common OS paths.
    Sets the global FONT_PATH variable.
    """
    global FONT_PATH
    # Prioritize bold fonts if available
    font_paths_to_try = [
        # Linux common paths
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSansBold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
        # MacOS common paths
        '/Library/Fonts/Arial Bold.ttf',
        '/System/Library/Fonts/HelveticaNeue.ttc', # May need index for bold
        '/Library/Fonts/Arial.ttf',
        '/System/Library/Fonts/Helvetica.ttc',
        # Windows common paths
        'C:/Windows/Fonts/arialbd.ttf',
        'C:/Windows/Fonts/ariblk.ttf',
        'C:/Windows/Fonts/arial.ttf',
        'C:/Windows/Fonts/verdana.ttf',
        # Fallback relative paths (if font is in the same dir as script)
        'DejaVuSans-Bold.ttf',
        'arialbd.ttf',
        'DejaVuSans.ttf',
        'arial.ttf',
    ]
    for path in font_paths_to_try:
        if path and os.path.exists(path):
            FONT_PATH = path
            print(f"Using font: {FONT_PATH}")
            return
    print("WARNING: No suitable TTF font found in common locations. Using Pillow's default bitmap font.")
    FONT_PATH = None # Explicitly set to None

def draw_word_clock(width, height, active_keys, grid_layout, word_positions):
    """
    Draws the word clock image based on the active keys and layout.
    Returns a PIL Image object.
    """
    image = Image.new('RGB', (width, height), COLOR_BACKGROUND)
    draw = ImageDraw.Draw(image)
    font_active = ImageFont.load_default() # Default fallback
    font_inactive = ImageFont.load_default()
    active_font_size = 10 # Default size

    grid_rows = len(grid_layout)
    if grid_rows == 0 or not grid_layout[0]:
        print("ERROR: Cannot draw clock, GRID_LAYOUT is empty or invalid.")
        return image # Return blank image
    grid_cols = len(grid_layout[0])
    if grid_cols == 0:
        print("ERROR: Cannot draw clock, GRID_LAYOUT columns are zero.")
        return image # Return blank image

    # Calculate font sizes dynamically based on grid and display dimensions
    if FONT_PATH:
        try:
            # Estimate max font size based on cell height
            cell_height_approx = height / grid_rows
            font_size = int(cell_height_approx * 0.75) # Start with 75% of cell height

            # Reduce font size until a character fits comfortably within a cell
            while font_size > MIN_INACTIVE_FONT_SIZE:
                font_test = ImageFont.truetype(FONT_PATH, font_size)
                # Use textbbox for more accurate size calculation if available (Pillow >= 8.0.0)
                try:
                    # Get bounding box for a wide character like 'W'
                    bbox = draw.textbbox((0, 0), "W", font=font_test)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                except AttributeError:
                    # Fallback for older Pillow versions
                    text_width, text_height = font_test.getsize("W")

                cell_width = width / grid_cols
                cell_height = height / grid_rows

                # Check if text fits within ~90% of cell dimensions
                if text_width < cell_width * 0.90 and text_height < cell_height * 0.90:
                    break # Found a suitable size
                font_size -= 2 # Decrease size and try again

            # Ensure font size doesn't go below minimum
            active_font_size = max(MIN_INACTIVE_FONT_SIZE + 1, font_size) # Active slightly larger maybe
            inactive_font_size = max(MIN_INACTIVE_FONT_SIZE, int(active_font_size * INACTIVE_FONT_SIZE_RATIO))

            # Load the final fonts
            font_active = ImageFont.truetype(FONT_PATH, active_font_size)
            font_inactive = ImageFont.truetype(FONT_PATH, inactive_font_size)
            # print(f"Using dynamic font sizes: Active={active_font_size}px, Inactive={inactive_font_size}px")

        except Exception as e:
            print(f"ERROR: Could not load font '{FONT_PATH}': {e}. Using default font.")
            # Fallback to default fonts already assigned
            font_active = ImageFont.load_default()
            font_inactive = ImageFont.load_default()
    else:
        # If no font path, stick with default fonts
        pass # Defaults already assigned

    # Determine which characters (row, col) should be active
    active_char_positions = set()
    for key in active_keys:
        if key in word_positions and word_positions[key]:
            # Ensure positions is always a list
            pos_list = word_positions[key] if isinstance(word_positions[key], list) else [word_positions[key]]
            for pos_info in pos_list:
                 if isinstance(pos_info, (list, tuple)) and len(pos_info) == 3:
                    row, start_col, end_col = pos_info
                    # Check bounds before adding characters
                    if 0 <= row < grid_rows and 0 <= start_col < grid_cols and 0 <= end_col < grid_cols and start_col <= end_col:
                        for col in range(start_col, end_col + 1):
                            active_char_positions.add((row, col))
                    else:
                         print(f"WARNING: Position {pos_info} for active key '{key}' is out of grid bounds. Skipping.")


    # Draw each character
    cell_width = width / grid_cols
    cell_height = height / grid_rows

    for r, row_str in enumerate(grid_layout):
        # Basic check for row validity
        if not isinstance(row_str, str) or len(row_str) != grid_cols:
            print(f"WARNING: Skipping drawing invalid grid row {r}: '{row_str}'")
            continue

        for c, char in enumerate(row_str):
            is_active = (r, c) in active_char_positions
            current_font = font_active if is_active else font_inactive
            text_color = COLOR_ACTIVE_TEXT if is_active else COLOR_INACTIVE_TEXT

            # Calculate center position for the character within its cell
            center_x = c * cell_width + cell_width / 2
            center_y = r * cell_height + cell_height / 2

            # Draw text centered using anchor='mm' (middle-middle) if possible (Pillow >= 8.0.0)
            try:
                draw.text(
                    (center_x, center_y),
                    char,
                    fill=text_color,
                    font=current_font,
                    anchor="mm" # Middle-Middle anchor
                )
            except TypeError:
                # Fallback for older Pillow versions that don't support anchor
                try:
                    # Calculate text size to manually center it
                    bbox = draw.textbbox((0, 0), char, font=current_font)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                except AttributeError:
                    text_width, text_height = current_font.getsize(char)

                # Calculate top-left corner for manual centering
                draw_x = center_x - text_width / 2
                draw_y = center_y - text_height / 2 # Simple baseline adjustment
                draw.text((draw_x, draw_y), char, fill=text_color, font=current_font)

    return image

def send_image_to_server(image_obj, ap_ip, mac_address, dither_val):
    """
    Processes the image (quantize, convert to RGB, save as JPEG) and sends it
    to the OpenEPaperLink AP server.
    Returns True on success, False otherwise.
    """
    start_time = time.time()
    url = f"http://{ap_ip}/imgupload"
    # Define a temporary filename for the JPEG
    temp_image_path = 'wordclock_temp_upload.jpg'

    # Define the 3-color palette (White, Black, Red) - common for some e-paper displays
    # Index 0: White (255, 255, 255)
    # Index 1: Black (0, 0, 0)
    # Index 2: Red   (255, 0, 0)
    # Fill the rest of the palette (up to 256 entries) - typically with black or white
    palette_data = [255, 255, 255, 0, 0, 0, 255, 0, 0]
    palette_data.extend([0, 0, 0] * (256 - len(palette_data) // 3)) # Fill remainder

    try:
        # Create a small palette image
        palette_img = Image.new('P', (1, 1))
        palette_img.putpalette(palette_data)

        # Quantize the image to the target palette
        # Use FLOYDSTEINBERG dithering during quantization if desired (usually better than server dither)
        # img_quantized = image_obj.quantize(palette=palette_img, dither=Image.FLOYDSTEINBERG)
        # Or let the server handle dithering if DITHER=1
        img_quantized = image_obj.quantize(palette=palette_img)


        # Convert the palettized image back to RGB before saving as JPEG
        # JPEG doesn't support palettes directly well.
        rgb_image = img_quantized.convert('RGB')

        # Save as JPEG with high quality
        # Note: JPEG is lossy, even at max quality. PNG might be better if server supports it,
        # but the example used JPEG.
        rgb_image.save(temp_image_path, 'JPEG', quality="maximum") # Pillow uses 1-95, "maximum" tries higher

        # Prepare payload for the POST request
        payload = {
            "dither": str(dither_val), # Ensure dither value is a string
            "mac": mac_address
        }

        # Open the saved JPEG file in binary read mode and send it
        print(f"Sending image '{temp_image_path}' to {url} for MAC {mac_address} (Dither={dither_val})...")
        with open(temp_image_path, "rb") as f_handle:
            files = {"file": f_handle}
            response = requests.post(url, data=payload, files=files, timeout=45) # Increased timeout slightly
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

        print(f"-> Image uploaded successfully! Status: {response.status_code}. Response: {response.text[:100]}...") # Show beginning of response
        duration = time.time() - start_time
        print(f"-> Upload duration: {duration:.2f}s")
        return True

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to send image: {e}")
        duration = time.time() - start_time
        print(f"-> Failed request duration: {duration:.2f}s")
        return False
    except FileNotFoundError:
        print(f"ERROR: Could not find the temporary image file '{temp_image_path}' for upload.")
        return False
    except IOError as e:
         print(f"ERROR: File I/O error during image processing/saving: {e}")
         return False
    except Exception as e:
        print(f"ERROR: Unexpected error during image processing or upload: {e}")
        duration = time.time() - start_time
        print(f"-> Failed operation duration: {duration:.2f}s")
        return False
    finally:
        # Clean up the temporary file if it exists
        print("Nothing to do here")

# =============================================================================
# TEST EXECUTION BLOCK
# =============================================================================
#if __name__ == "__main__":
#    print("--- Word Clock Combination Tester ---")
#
#    # --- Test Setup ---
#    OUTPUT_DIR = "word_clock_test_images"
#    # Ensure output directory exists
#    os.makedirs(OUTPUT_DIR, exist_ok=True)
#    print(f"Output images will be saved to: {OUTPUT_DIR}")
#
#    # Find the font once
#    find_font()
#
#    # Keep track of unique combinations found (using frozenset for hashability)
#    # Store the first time (HHMM) the combination was generated
#    unique_combinations = {}
#    combination_counter = 0
#
#    print("\nIterating through all hours (0-23) and minutes (0-59)...")
#
#    start_time = time.time()
#
#    # Loop through every possible minute of a day
#    for hour in range(24):
#        for minute in range(60):
#            # 1. Get the active words for this specific time
#            active_keys = get_active_words(hour, minute, HOUR_WORDS)
#
#            # 2. Create a unique, order-independent representation of the keys
#            #    We use a frozenset of the sorted keys.
#            combination_id = frozenset(sorted(active_keys))
#
#            # 3. Check if we've seen this combination before
#            if combination_id not in unique_combinations:
#                combination_counter += 1
#                first_time_str = f"{hour:02d}{minute:02d}"
#                unique_combinations[combination_id] = first_time_str # Store the first time it occurred
#
#                print(f"\n#{combination_counter}: Found new unique combination for time {first_time_str}")
#                print(f"   Active Keys: {sorted(active_keys)}")
#
#                # 4. Generate the image for this unique combination
#                clock_image = draw_word_clock(
#                    DISPLAY_WIDTH, DISPLAY_HEIGHT, active_keys,
#                    GRID_LAYOUT, WORD_POSITIONS
#                )
#
#                # 5. Create a filename
#                #    Includes counter, first time, and sanitized key list
#                keys_str_part = "_".join(sorted(active_keys))
#                # Sanitize keys_str_part for filename (remove invalid chars)
#                sanitized_keys_str = re.sub(r'[\\/*?:"<>|]', "", keys_str_part)
#                sanitized_keys_str = sanitized_keys_str[:80] # Limit length
#
#                # Format: 001_HHMM_KEY1_KEY2... .png
#                filename = f"{combination_counter:03d}_{first_time_str}_{sanitized_keys_str}.png"
#                filepath = os.path.join(OUTPUT_DIR, filename)
#
#                # 6. Save the image (use PNG for lossless quality)
#                try:
#                    clock_image.save(filepath, 'PNG')
#                    print(f"   -> Saved: {filepath}")
#                except Exception as e:
#                    print(f"   ERROR: Failed to save image {filepath}: {e}")
#
#    end_time = time.time()
#    duration = end_time - start_time
#
#    print("\n--- Testing Complete ---")
#    print(f"Total unique word combinations found: {len(unique_combinations)}")
#    print(f"Total time taken: {duration:.2f} seconds")
#    print(f"Images saved in: {os.path.abspath(OUTPUT_DIR)}")





# =============================================================================
# MAIN EXECUTION BLOCK
# =============================================================================
if __name__ == "__main__":
    print("--- Word Clock for OpenEPaperLink Starting ---")

    # 1. Find a usable font
    find_font()

    # 2. Verify the layout definitions (Crucial step!)
    # This checks if WORD_POSITIONS correctly points to the expected letters
    # in GRID_LAYOUT based on INTERNAL_KEY_TO_WORD mapping.
    if not verify_layout(GRID_LAYOUT, WORD_POSITIONS, INTERNAL_KEY_TO_WORD):
        print("FATAL: Layout verification failed. Please fix errors in the definitions above.")
        sys.exit(1) # Exit if layout is broken

    # 3. Print configuration summary
    print("\n--- Configuration ---")
    print(f"Display Size: {DISPLAY_WIDTH}x{DISPLAY_HEIGHT}")
    print(f"Target AP IP: {AP_IP}")
    print(f"Target MAC:   {TARGET_MAC}")
    print(f"Server Dither:{'On' if DITHER == 1 else 'Off'}")
    print(f"Using Font:   {FONT_PATH if FONT_PATH else 'Pillow Default'}")
    print(f"Check Interval: {CHECK_INTERVAL_SECONDS} seconds")
    print("---------------------\n")

    last_minute_checked = -1
    last_sent_image_hash = None # Use hash to compare images efficiently

    try:
        while True:
            # Get current time
            now = datetime.datetime.now()
            current_minute = now.minute

            # Only proceed if the minute has changed since the last check
            if current_minute != last_minute_checked:
                print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Minute changed to {current_minute}. Generating image...")

                # Calculate active words based on current time
                active_keys = get_active_words(now.hour, now.minute, HOUR_WORDS)
                print(f"Active keys: {active_keys}")

                # Draw the word clock image
                clock_image = draw_word_clock(
                    DISPLAY_WIDTH, DISPLAY_HEIGHT, active_keys,
                    GRID_LAYOUT, WORD_POSITIONS
                )

                # Check if the image has actually changed since the last successful send
                try:
                    current_image_bytes = clock_image.tobytes()
                    # Using hash is generally faster for large images than direct byte comparison
                    current_image_hash = hash(current_image_bytes)
                except Exception as e:
                    print(f"ERROR: Could not get image bytes or hash: {e}")
                    current_image_hash = None # Force retry if hashing fails

                if current_image_hash is not None and current_image_hash != last_sent_image_hash:
                    print("-> Image content has changed. Attempting upload...")
                    send_successful = send_image_to_server(clock_image, AP_IP, TARGET_MAC, DITHER)

                    if send_successful:
                        last_sent_image_hash = current_image_hash # Store hash of successfully sent image
                        print("-> Upload successful. Updated last sent image hash.")
                    else:
                        print("-> Upload failed. Will retry on the next minute change.")
                        # Optionally clear last_sent_image_hash to force retry even if next image is same
                        # last_sent_image_hash = None
                elif current_image_hash is None:
                     print("-> Could not generate image hash. Skipping comparison, attempting upload...")
                     # Attempt send anyway if hashing failed
                     send_successful = send_image_to_server(clock_image, AP_IP, TARGET_MAC, DITHER)
                     if send_successful: print("-> Upload successful despite hash issue.")
                     else: print("-> Upload failed.")
                else:
                    print("-> Image content unchanged since last successful upload. Skipping.")

                # Update the last checked minute *after* processing
                last_minute_checked = current_minute

            # Wait before checking the time again
            time.sleep(CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\n--- Word Clock stopped by user (Ctrl+C) ---")
    except Exception as e:
        # Catch any unexpected errors in the main loop
        print(f"\n--- FATAL ERROR in main loop ---")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Details: {e}")
        import traceback
        traceback.print_exc() # Print detailed traceback
        print("------------------------------------")
    finally:
        print("Exiting Word Clock script.")