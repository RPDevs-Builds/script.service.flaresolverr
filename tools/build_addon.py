import os
import zipfile
import xml.etree.ElementTree as ET
import sys

def get_addon_info(addon_path):
    tree = ET.parse(os.path.join(addon_path, 'addon.xml'))
    root = tree.getroot()
    return root.attrib['id'], root.attrib['version']

def create_zip():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    addon_id, version = get_addon_info(base_dir)
    
    zip_filename = f"{addon_id}-{version}.zip"
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(base_dir):
            if '.git' in root or '__pycache__' in root or 'tools' in root:
                continue
                
            for file in files:
                if file.endswith('.zip') or file.startswith('.'):
                    continue
                    
                file_path = os.path.join(root, file)
                arcname = os.path.join(addon_id, os.path.relpath(file_path, base_dir))
                zipf.write(file_path, arcname)
                
    print(f"::set-output name=zip_path::{zip_filename}")
    print(f"::set-output name=version::{version}")
    print(f"Created {zip_filename}")

if __name__ == '__main__':
    create_zip()
