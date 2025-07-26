import argparse
from pathlib import Path
import sys
import json
from marker.config.parser import ConfigParser
from marker.output import save_output
from marker.models import create_model_dict # Already added, but for context
from marker.config.parser import ConfigParser
from marker.renderers.markdown import MarkdownOutput
from marker.renderers.html import HTMLOutput
from marker.renderers.json import JSONOutput
from marker.renderers.chunk import ChunkOutput
from marker.renderers.ocr_json import OCRJSONOutput
from marker.renderers.extraction import ExtractionOutput
from marker.settings import settings
from PIL import Image
import io

def get_default_output_dir(input_path: Path) -> Path:
    """
    Generate default output directory path based on input PDF path.
    Creates a directory with same name as PDF (without extension) next to the PDF.
    """
    return input_path.parent / input_path.stem

def get_default_input_dir() -> Path:
    """
    Get default input directory (./input) relative to current working directory.
    Creates it if it doesn't exist.
    """
    input_dir = Path.cwd() / 'input'
    input_dir.mkdir(exist_ok=True)
    return input_dir


def save_images(images: dict, image_dir: Path) -> None:
    """
    Save images with proper error handling and format detection.
    Preserves original image filenames from the input.
    
    Args:
        images: Dictionary of images from marker-pdf conversion where keys are filenames
        image_dir: Directory to save images to
    """
    if not images:
        print("No images found in document")
        return
        
    image_dir.mkdir(exist_ok=True)
    saved_count = 0
    
    for filename, image_data in images.items():
        try:
            # Skip if image data is None or empty
            if not image_data:
                continue
                
            image_path = image_dir / filename
            
            # Handle different image data formats
            if isinstance(image_data, Image.Image):
                image_data.save(image_path)
                saved_count += 1
                    
            elif isinstance(image_data, bytes):
                img = Image.open(io.BytesIO(image_data))
                img.save(image_path)
                saved_count += 1
                    
            elif isinstance(image_data, str):
                if Path(image_data).exists():
                    img = Image.open(image_data)
                    img.save(image_path)
                    saved_count += 1
                else:
                    print(f"Image path does not exist: {image_data}")
            else:
                print(f"Unsupported image data type for {filename}: {type(image_data)}")
                
        except Exception as e:
            print(f"Error saving image {filename}: {str(e)}")
            continue
            
    if saved_count > 0:
        print(f"Successfully saved {saved_count} images to: {image_dir}")
    else:
        print("No valid images were found to save")


# Helper function to unpack the rendered output from marker
def text_from_rendered(rendered):
    if isinstance(rendered, MarkdownOutput):
        return rendered.markdown, "md", rendered.images
    elif isinstance(rendered, HTMLOutput):
        return rendered.html, "html", rendered.images
    elif isinstance(rendered, (JSONOutput, ChunkOutput, OCRJSONOutput, ExtractionOutput)):
        return rendered.model_dump_json(exclude=["metadata"], indent=2), "json", {}
    else:
        raise ValueError(f"Unsupported output type: {type(rendered)}")

# Helper function to ensure images are in a save-compatible format
def convert_if_not_rgb(image: Image.Image) -> Image.Image:
    if image.mode != "RGB":
        image = image.convert("RGB")
    return image

def save_converted_output(rendered, output_dir: Path, fname_base: str):
    """
    Saves all output (markdown, images, metadata) to the specified directory.
    This function is a robust, local replacement for the library's save_output.
    """
    # 1. CRITICAL STEP: Ensure the output directory exists.
    output_dir.mkdir(parents=True, exist_ok=True)

    # 2. Unpack the rendered data
    text_content, extension, images = text_from_rendered(rendered)
    
    # Ensure text is properly encoded
    text_content = text_content.encode(settings.OUTPUT_ENCODING, errors="replace").decode(
        settings.OUTPUT_ENCODING
    )

    # 3. Save the main text file (e.g., markdown)
    main_file_path = output_dir / f"{fname_base}.{extension}"
    main_file_path.write_text(text_content, encoding=settings.OUTPUT_ENCODING)

    # 4. Save the metadata file
    meta_file_path = output_dir / f"{fname_base}_meta.json"
    meta_file_path.write_text(json.dumps(rendered.metadata, indent=2), encoding=settings.OUTPUT_ENCODING)

    # 5. Save all images
    if images:
        # Create an 'images' subdirectory for organization
        image_dir = output_dir / 'images'
        image_dir.mkdir(exist_ok=True)
        for img_name, img_obj in images.items():
            img_obj = convert_if_not_rgb(img_obj)
            # It's better to save images in their own folder
            img_path = image_dir / img_name
            img_obj.save(img_path, settings.OUTPUT_IMAGE_FORMAT)


def convert_pdf(
    input_path: str,
    output_dir: Path,
    models: dict,
    batch_multiplier: int,
    max_pages: int,
    langs: str
):
    """
    Converts a single PDF using the marker library's official components.

    Args:
        input_path: Path to the PDF file.
        output_dir: Directory to save the output.
        models: Pre-loaded dictionary of models.
        ... other settings
    """
    try:
        # 1. Create a dictionary of settings for ConfigParser
        #    This mimics how the CLI passes arguments
        settings = {
            "langs": langs.split(",") if langs else None,
            "max_pages": max_pages,
            "batch_multiplier": batch_multiplier,
        }
        # Filter out None values so we don't override library defaults
        settings = {k: v for k, v in settings.items() if v is not None}

        # 2. Use ConfigParser to handle all configuration
        config_parser = ConfigParser(settings)

        # 3. Get the converter class and instantiate it correctly
        converter_cls = config_parser.get_converter_cls()
        converter = converter_cls(
            config=config_parser.generate_config_dict(),
            artifact_dict=models,  # Pass in the pre-loaded models
        )
        print(f"Using converter: {converter_cls.__name__}")

        # 4. Run the conversion. The converter is a callable class.
        rendered = converter(input_path)

        print(f"Conversion completed for: {input_path}")

        # Use our new local save function
        base_filename = config_parser.get_base_filename(input_path)
        save_converted_output(rendered, output_dir, base_filename)

        print(f"✅ Successfully saved output to: {output_dir}")

    except Exception as e:
        print(f"❌ Error converting {input_path}: {type(e).__name__} - {e}", file=sys.stderr)

    
def add_pdfs_to_queue(input_path: Path) -> list[Path]:
    """
    Add PDF files to the processing queue.
    If input_path is a directory, add all PDFs in it.
    If input_path is a file, add just that file.
    """
    queue = []
    
    if input_path.is_dir():
        pdfs = list(input_path.glob('*.pdf'))
        if not pdfs:
            print(f"No PDF files found in directory: {input_path}", file=sys.stderr)
            sys.exit(1)
        queue.extend(pdfs)
    else:
        if not input_path.is_file():
            print(f"Error: Input file does not exist: {input_path}", file=sys.stderr)
            sys.exit(1)
        if input_path.suffix.lower() != '.pdf':
            print(f"Error: Input file must be a PDF: {input_path}", file=sys.stderr)
            sys.exit(1)
        queue.append(input_path)
        
    return queue
