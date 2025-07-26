#!/usr/bin/env python3
import argparse
from pathlib import Path
import modules.pdf2md as pdf2md
import modules.mark2epub as mark2epub
from marker.models import create_model_dict
import torch
                


def main():
    # --- Argument parsing and device check (no changes here) ---
    if torch.cuda.is_available():
        print("CUDA is available. Using GPU for processing.")
    elif torch.mps.is_available():
        print("MPS is available. Using Apple Silicon for processing.")
    else:
        print("CUDA is not available. Using CPU for processing.")
        
    parser = argparse.ArgumentParser(
        description='Convert PDF files to EPUB format via Markdown'
    )
    # (All your parser.add_argument calls remain the same)
    parser.add_argument('input_path', nargs='?', type=str, help='Path to input PDF file or directory (default: ./input/*.pdf)')
    parser.add_argument('output_path', nargs='?', type=str, help='Path to output directory (default: ./output)')
    parser.add_argument('--batch-multiplier', type=int, default=2, help='Multiplier for batch size')
    parser.add_argument('--max-pages', type=int, default=None, help='Maximum number of pages to process')
    parser.add_argument('--start-page', type=int, default=None, help='Page number to start from')
    parser.add_argument('--langs', type=str, default=None, help='Comma-separated list of languages')
    parser.add_argument('--skip-epub', action='store_true', help='Skip EPUB generation')
    parser.add_argument('--skip-md', action='store_true', help='Skip markdown generation')
    
    args = parser.parse_args()
    
    # --- Path and Model Setup ---
    input_path = Path(args.input_path) if args.input_path else pdf2md.get_default_input_dir()
    queue = pdf2md.add_pdfs_to_queue(input_path)
    print(f"Found {len(queue)} PDF files to process")
    
    print("Loading models (this may take a moment)...")
    models = create_model_dict()
    print("Models loaded successfully.")
    
    # =========================================================
    # 1. ESTABLISH A CLEAR, TOP-LEVEL OUTPUT DIRECTORY
    # =========================================================
    if args.output_path:
        top_level_output_dir = Path(args.output_path)
    else:
        # Use a sensible default like './output' if no path is provided
        top_level_output_dir = Path.cwd() / 'output'
    top_level_output_dir.mkdir(exist_ok=True)


    # --- Processing Loop ---
    for pdf_path in queue:
        print(f"\nProcessing: {pdf_path.name}")
        
        # =========================================================
        # 2. DEFINE A SPECIFIC MARKDOWN DIRECTORY FOR THIS PDF
        #    This is where intermediate files (.md, images) will go.
        # =========================================================
        markdown_dir = top_level_output_dir / pdf_path.stem
              
        try:
            if not args.skip_md:
                print("Converting PDF to Markdown...")
                pdf2md.convert_pdf(
                    input_path=str(pdf_path),
                    output_dir=markdown_dir,
                    models=models,
                    batch_multiplier=args.batch_multiplier,
                    max_pages=args.max_pages,
                    langs=args.langs
                )
            elif not markdown_dir.exists():
                print(f"Error: --skip-md was used, but markdown directory not found: {markdown_dir}")
                continue

            if not args.skip_epub:
                print("Converting Markdown to EPUB...")
                # The epub module takes the markdown folder and the top-level output folder
                mark2epub.convert_to_epub(markdown_dir, top_level_output_dir)
                
        except Exception as e:
            print(f"Error processing {pdf_path.name}: {str(e)}")
            continue

if __name__ == '__main__':
    main()