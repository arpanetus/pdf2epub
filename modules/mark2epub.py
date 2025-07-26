import markdown
import os
from xml.dom import minidom
import zipfile
import sys
import json
from PIL import Image
import regex as re
from pathlib import Path
from datetime import datetime
import subprocess
from typing import Dict, Optional, Tuple

def get_user_input(prompt: str, default: str = "") -> str:
    """Get user input with a default value."""
    user_input = input(f"{prompt} [{default}]: ").strip()
    return user_input if user_input else default

def get_metadata_from_user(existing_metadata: Optional[Dict] = None) -> Dict:
    """Interactively collect metadata from user with defaults from existing metadata."""
    if existing_metadata is None:
        existing_metadata = {}
    
    metadata = existing_metadata.get("metadata", {})
    
    print("\nPlease provide the following metadata for your EPUB (press Enter to use default value):")
    
    fields = {
        "dc:title": ("Title", metadata.get("dc:title", "Untitled Document")),
        "dc:creator": ("Author(s)", metadata.get("dc:creator", "Unknown Author")),
        "dc:identifier": ("Unique Identifier", metadata.get("dc:identifier", f"id-{datetime.now().strftime('%Y%m%d%H%M%S')}")),
        "dc:language": ("Language (e.g., en, de, fr)", metadata.get("dc:language", "en")),
        "dc:rights": ("Rights", metadata.get("dc:rights", "All rights reserved")),
        "dc:publisher": ("Publisher", metadata.get("dc:publisher", "PDF2EPUB")),
        "dc:date": ("Publication Date (YYYY-MM-DD)", metadata.get("dc:date", datetime.now().strftime("%Y-%m-%d")))
    }
    
    updated_metadata = {}
    for key, (prompt, default) in fields.items():
        value = get_user_input(prompt, default)
        updated_metadata[key] = value
        
    return {
        "metadata": updated_metadata,
        "default_css": existing_metadata.get("default_css", []),
        "chapters": existing_metadata.get("chapters", []),
        "cover_image": existing_metadata.get("cover_image", None)
    }

def review_markdown(markdown_path: Path) -> tuple[bool, str]:
    """Ask user if they want to review the markdown file."""
    content = markdown_path.read_text(encoding='utf-8')
    
    while True:
        response = input("\nWould you like to review the markdown file before conversion? (y/n): ").lower()
        if response in ['y', 'yes']:
            try:
                subprocess.run(['xdg-open' if os.name == 'posix' else 'start', str(markdown_path)], check=True)
                
                while True:
                    proceed = input("\nPress Enter when you're done editing (or 'q' to abort): ").lower()
                    if proceed == 'q':
                        return False, content
                    elif proceed == '':
                        updated_content = markdown_path.read_text(encoding='utf-8')
                        return True, updated_content
            except Exception as e:
                print(f"\nError opening markdown file: {e}")
                print("Proceeding with conversion...")
                return True, content
        elif response in ['n', 'no']:
            return True, content
        else:
            print("Please enter 'y' or 'n'")

def process_markdown_for_images(markdown_text: str, work_dir: Path) -> tuple[str, list[str]]:
    """Process markdown content to find image references."""
    image_pattern = r'!\[(.*?)\]\((.*?)\)'
    images_found = []
    modified_text = markdown_text
    
    for match in re.finditer(image_pattern, markdown_text):
        alt_text, image_path = match.groups()
        image_path = image_path.strip()
        img_path = Path(image_path)
        
        # Correctly find the image in the 'images' subdirectory
        full_image_path = work_dir / 'images' / img_path.name
        if full_image_path.exists():
            images_found.append(img_path.name)
            # Ensure the new reference points to the 'images' folder in the EPUB
            new_ref = f'![{alt_text}](images/{img_path.name})'
            modified_text = modified_text.replace(match.group(0), new_ref)
        else:
            print(f"Warning: Image not found: {full_image_path}")
    
    return modified_text, images_found

def copy_and_optimize_image(src_path: Path, dest_path: Path, max_dimension: int = 1800) -> None:
    """Copy image to destination path with optimization for EPUB."""
    try:
        with Image.open(src_path) as img:
            if img.mode == 'RGBA':
                img = img.convert('RGB')
                
            ratio = min(max_dimension / max(img.size[0], img.size[1]), 1.0)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            
            if ratio < 1.0:
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            if src_path.suffix.lower() in ['.jpg', '.jpeg']:
                img.save(dest_path, 'JPEG', quality=85, optimize=True)
            elif src_path.suffix.lower() == '.png':
                img.save(dest_path, 'PNG', optimize=True)
            else:
                dest_path = dest_path.with_suffix('.jpg')
                img.save(dest_path, 'JPEG', quality=85, optimize=True)
                
    except Exception as e:
        print(f"Error processing image {src_path}: {e}")
        raise

def get_all_filenames(the_dir, extensions=[]):
    if not os.path.exists(the_dir):
        return []
    all_files = [x for x in os.listdir(the_dir)]
    all_files = [x for x in all_files if x.split(".")[-1] in extensions]
    return all_files

def get_packageOPF_XML(md_filenames=[], image_filenames=[], css_filenames=[], description_data=None):
    doc = minidom.Document()

    package = doc.createElement('package')
    package.setAttribute('xmlns',"http://www.idpf.org/2007/opf")
    package.setAttribute('version',"3.0")
    package.setAttribute('xml:lang',"en")
    package.setAttribute("unique-identifier","pub-id")

    # Now building the metadata
    metadata = doc.createElement('metadata')
    metadata.setAttribute('xmlns:dc', 'http://purl.org/dc/elements/1.1/')

    for k,v in description_data["metadata"].items():
        if len(v):
            x = doc.createElement(k)
            for metadata_type,id_label in [("dc:title","title"),("dc:creator","creator"),("dc:identifier","book-id")]:
                if k==metadata_type:
                    x.setAttribute('id',id_label)
            x.appendChild(doc.createTextNode(v))
            metadata.appendChild(x)

    # Now building the manifest
    manifest = doc.createElement('manifest')

    # TOC.xhtml file for EPUB 3
    x = doc.createElement('item')
    x.setAttribute('id',"toc")
    x.setAttribute('properties',"nav")
    x.setAttribute('href',"TOC.xhtml")
    x.setAttribute('media-type',"application/xhtml+xml")
    manifest.appendChild(x)

    # Ensure retrocompatibility by also providing a TOC.ncx file
    x = doc.createElement('item')
    x.setAttribute('id',"ncx")
    x.setAttribute('href',"toc.ncx")
    x.setAttribute('media-type',"application/x-dtbncx+xml")
    manifest.appendChild(x)

    x = doc.createElement('item')
    x.setAttribute('id',"titlepage")
    x.setAttribute('href',"titlepage.xhtml")
    x.setAttribute('media-type',"application/xhtml+xml")
    manifest.appendChild(x)

    for i,md_filename in enumerate(md_filenames):
        x = doc.createElement('item')
        x.setAttribute('id',"s{:05d}".format(i))
        x.setAttribute('href',"s{:05d}-{}.xhtml".format(i,md_filename.split(".")[0]))
        x.setAttribute('media-type',"application/xhtml+xml")
        manifest.appendChild(x)

    for i,image_filename in enumerate(image_filenames):
        x = doc.createElement('item')
        x.setAttribute('id',"image-{:05d}".format(i))
        x.setAttribute('href',"images/{}".format(image_filename))
        if "gif" in image_filename:
            x.setAttribute('media-type',"image/gif")
        elif "jpg" in image_filename or "jpeg" in image_filename:
            x.setAttribute('media-type',"image/jpeg")
        elif "png" in image_filename:
            x.setAttribute('media-type',"image/png")
        if image_filename==description_data.get("cover_image"):
            x.setAttribute('properties',"cover-image")
            # Ensure compatibility by also providing a meta tag in the metadata
            y = doc.createElement('meta')
            y.setAttribute('name',"cover")
            y.setAttribute('content',"image-{:05d}".format(i))
            metadata.appendChild(y)
        manifest.appendChild(x)

    for i,css_filename in enumerate(css_filenames):
        x = doc.createElement('item')
        x.setAttribute('id',"css-{:05d}".format(i))
        x.setAttribute('href',"css/{}".format(css_filename))
        x.setAttribute('media-type',"text/css")
        manifest.appendChild(x)

    # Now building the spine
    spine = doc.createElement('spine')
    spine.setAttribute('toc', "ncx")

    x = doc.createElement('itemref')
    x.setAttribute('idref',"titlepage")
    x.setAttribute('linear',"yes")
    spine.appendChild(x)
    for i,md_filename in enumerate(md_filenames):
        x = doc.createElement('itemref')
        x.setAttribute('idref',"s{:05d}".format(i))
        x.setAttribute('linear',"yes")
        spine.appendChild(x)

    guide = doc.createElement('guide')
    x = doc.createElement('reference')
    x.setAttribute('type',"cover")
    x.setAttribute('title',"Cover image")
    x.setAttribute('href',"titlepage.xhtml")
    guide.appendChild(x)

    package.appendChild(metadata)
    package.appendChild(manifest)
    package.appendChild(spine)
    package.appendChild(guide)
    doc.appendChild(package)

    return doc.toprettyxml()

def get_container_XML():
    return """<?xml version="1.0" encoding="UTF-8" ?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles>
<rootfile full-path="OPS/package.opf" media-type="application/oebps-package+xml"/>
</rootfiles>
</container>"""

def get_coverpage_XML(title, authors):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">
<head>
<title>Cover Page</title>
<style type="text/css">
body {{ 
    margin: 0;
    padding: 0;
    height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    font-family: serif;
}}
.cover {{
    padding: 3em;
    text-align: center;
    border: 1px solid #ccc;
    max-width: 80%;
}}
h1 {{
    font-size: 2em;
    margin-bottom: 1em;
    line-height: 1.2;
    color: #333;
}}
p {{
    font-size: 1.2em;
    font-style: italic;
    color: #666;
    line-height: 1.4;
}}
</style>
</head>
<body>
    <div class="cover">
        <h1>{title}</h1>
        <p>{authors}</p>
    </div>
</body>
</html>"""

def get_TOC_XML(default_css_filenames, markdown_filenames):
    toc_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">
<head>
<meta http-equiv="default-style" content="text/html; charset=utf-8"/>
<title>Contents</title>
"""
    for css_filename in default_css_filenames:
        toc_xhtml += f"""<link rel="stylesheet" href="css/{css_filename}" type="text/css"/>\n"""
    toc_xhtml += """</head>
<body>
<nav epub:type="toc" role="doc-toc" id="toc">
<h2>Contents</h2>
<ol epub:type="list">"""
    for i,md_filename in enumerate(markdown_filenames):
        toc_xhtml += f"""<li><a href="s{i:05d}-{md_filename.split(".")[0]}.xhtml">{md_filename.split(".")[0]}</a></li>"""
    toc_xhtml += """</ol>
</nav>
</body>
</html>"""
    return toc_xhtml

def get_TOCNCX_XML(markdown_filenames):
    toc_ncx = """<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" xml:lang="fr" version="2005-1">
<head>
</head>
<navMap>
"""
    for i,md_filename in enumerate(markdown_filenames):
        toc_ncx += f"""<navPoint id="navpoint-{i}">
<navLabel>
<text>{md_filename.split(".")[0]}</text>
</navLabel><content src="s{i:05d}-{md_filename.split(".")[0]}.xhtml"/>
</navPoint>"""
    toc_ncx += """</navMap>
</ncx>"""
    return toc_ncx

def get_chapter_XML(work_dir: str, md_filename: str, css_filenames: list[str], content: Optional[str] = None) -> tuple[str, list[str]]:
    """
    Convert markdown chapter to XHTML and process images.
    Returns tuple of (XHTML content, list of images referenced in chapter)
    """
    work_dir_path = Path(work_dir)
    
    if content is None:
        markdown_data = (work_dir_path / md_filename).read_text(encoding="utf-8")
    else:
        markdown_data = content
    
    # ==================== ADD THIS FIX ====================
    # Preprocess the markdown to ensure paragraphs are separated by blank lines.
    # This forces the markdown converter to wrap each line in a <p> tag.
    lines = markdown_data.strip().split('\n')
    corrected_markdown = "\n\n".join(lines)
    # ======================================================

    # Process the corrected markdown for images and get list of referenced images
    final_markdown, chapter_images = process_markdown_for_images(corrected_markdown, work_dir_path)
    
    # Convert the fully processed markdown to HTML
    html_text = markdown.markdown(
        final_markdown,
        extensions=["codehilite", "tables", "fenced_code", "footnotes"],
        extension_configs={"codehilite": {"guess_lang": False}}
    )

    # Generate XHTML wrapper
    xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en">
<head>
    <meta http-equiv="default-style" content="text/html; charset=utf-8"/>
    <title>{md_filename.split(".")[0]}</title>
    {''.join(f'<link rel="stylesheet" href="css/{css}" type="text/css" media="all"/>' for css in css_filenames)}
</head>
<body>
{html_text}
</body>
</html>"""

    return xhtml, chapter_images

def convert_to_epub(markdown_dir: Path, output_dir: Path) -> None:
    if not markdown_dir.exists():
        raise FileNotFoundError(f"Markdown directory not found: {markdown_dir}")
        
    if not list(markdown_dir.glob('*.md')):
        raise ValueError(f"No markdown files found in: {markdown_dir}")
    
    # The final EPUB will be placed in the parent output_dir, named after the markdown_dir
    epub_path = output_dir / f"{markdown_dir.name}.epub"
    main([str(markdown_dir), str(epub_path)])

def main(args):
    if len(args) < 2:
        print("\nUsage:\n    python md2epub.py <markdown_directory> <output_file.epub>")
        exit(1)

    work_dir = args[0]
    output_path = args[1]

    # == CHANGE 1: Automatically create stylesheet for indentation ==
    css_dir_path = Path(work_dir) / 'css'
    css_dir_path.mkdir(exist_ok=True)
    
    stylesheet_path = css_dir_path / "stylesheet.css"
    indent_css = """
p {
  text-indent: 1.5em;
  margin-top: 0;
  margin-bottom: 0;
}

/* For starting chapters/sections on a new page */
h1, h2, h3, h4 {
  page-break-before: always;
  text-align: center;
  margin-top: 3em;
  margin-bottom: 1.5em;
  line-height: 1.2;
}
"""
    if not stylesheet_path.exists():
        print("Creating default stylesheet for paragraph indentation...")
        stylesheet_path.write_text(indent_css, encoding='utf-8')
    # =============================================================

    images_dir = os.path.join(work_dir, 'images/')
    css_dir = str(css_dir_path)

    try:
        description_path = os.path.join(work_dir, "description.json")
        existing_metadata = {}
        if os.path.exists(description_path):
            with open(description_path, 'r', encoding='utf-8') as f:
                existing_metadata = json.load(f)
        
        json_data = get_metadata_from_user(existing_metadata)
        
        # == CHANGE 2: Ensure our stylesheet is always included ==
        if "stylesheet.css" not in json_data.get("default_css", []):
            if "default_css" not in json_data:
                json_data["default_css"] = []
            json_data["default_css"].append("stylesheet.css")
        # ========================================================
        
        if not json_data["chapters"]:
            markdown_files = [f for f in os.listdir(work_dir) if f.endswith('.md')]
            for md_file in sorted(markdown_files):
                json_data["chapters"].append({"markdown": md_file, "css": ""})
        
        with open(description_path, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2)
        
        chapter_contents = {}
        for chapter in json_data["chapters"]:
            md_path = Path(work_dir) / chapter["markdown"]
            should_continue, content = review_markdown(md_path)
            if not should_continue:
                print("\nConversion aborted by user.")
                return
            chapter_contents[chapter["markdown"]] = content

        title = json_data["metadata"].get("dc:title", "Untitled Document")
        authors = json_data["metadata"].get("dc:creator", "Unknown Author")

        all_md_filenames = [ch["markdown"] for ch in json_data["chapters"]]
        all_css_filenames = list(dict.fromkeys(json_data["default_css"]))

        # Process chapters to find all referenced images
        all_referenced_images = set()
        chapter_data = {}
        print("\nProcessing chapters and collecting image references...")
        for chapter in json_data["chapters"]:
            md_filename = chapter["markdown"]
            css_files = json_data["default_css"]
            chapter_xhtml, chapter_images = get_chapter_XML(
                work_dir, md_filename, css_files, content=chapter_contents[md_filename]
            )
            chapter_data[md_filename] = chapter_xhtml
            all_referenced_images.update(chapter_images)
            
        print("\nCreating EPUB file...")
        with zipfile.ZipFile(output_path, "w") as epub:
            epub.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            epub.writestr("META-INF/container.xml", get_container_XML(), compress_type=zipfile.ZIP_DEFLATED)
            
            # Get list of all images available in the images directory
            all_available_images = get_all_filenames(images_dir, extensions=["gif", "jpg", "jpeg", "png"])
            
            epub.writestr("OPS/package.opf", 
                get_packageOPF_XML(
                    md_filenames=all_md_filenames,
                    image_filenames=all_available_images,
                    css_filenames=all_css_filenames,
                    description_data=json_data
                ), 
                compress_type=zipfile.ZIP_DEFLATED
            )
            epub.writestr("OPS/titlepage.xhtml", get_coverpage_XML(title, authors).encode('utf-8'), compress_type=zipfile.ZIP_DEFLATED)
            
            print("Writing chapters...")
            for i, md_filename in enumerate(all_md_filenames):
                epub.writestr(
                    f"OPS/s{i:05d}-{md_filename.split('.')[0]}.xhtml",
                    chapter_data[md_filename].encode('utf-8'),
                    compress_type=zipfile.ZIP_DEFLATED
                )
            
            if all_available_images:
                print(f"Writing {len(all_available_images)} images...")
                for image_name in all_available_images:
                    src_path = Path(images_dir) / image_name
                    with open(src_path, "rb") as f:
                        epub.writestr(f"OPS/images/{image_name}", f.read(), compress_type=zipfile.ZIP_DEFLATED)

            print("Writing table of contents...")
            epub.writestr("OPS/TOC.xhtml", 
                get_TOC_XML(all_css_filenames, all_md_filenames).encode('utf-8'),
                compress_type=zipfile.ZIP_DEFLATED
            )
            epub.writestr("OPS/toc.ncx",
                get_TOCNCX_XML(all_md_filenames).encode('utf-8'),
                compress_type=zipfile.ZIP_DEFLATED
            )
            
            if os.path.exists(css_dir):
                print(f"Writing {len(all_css_filenames)} CSS files...")
                for css in all_css_filenames:
                    css_path = os.path.join(css_dir, css)
                    if os.path.exists(css_path):
                        with open(css_path, "rb") as f:
                            epub.writestr(f"OPS/css/{css}", f.read(), compress_type=zipfile.ZIP_DEFLATED)

        print(f"\nEPUB creation complete: {output_path}")
        
    except Exception as e:
        import traceback
        print(f"Error processing {work_dir}:")
        print(traceback.format_exc())
        raise

if __name__ == "__main__":
    main(sys.argv[1:])