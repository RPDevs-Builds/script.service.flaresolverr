import os
import sys
import shutil
import filecmp
import xml.etree.ElementTree as ET

def update_addon_version(addon_xml_path):
    tree = ET.parse(addon_xml_path)
    root = tree.getroot()
    version = root.attrib.get('version', '1.0.0')
    
    # Increment patch version
    parts = version.split('.')
    if len(parts) >= 3:
        parts[2] = str(int(parts[2]) + 1)
        new_version = '.'.join(parts)
        root.attrib['version'] = new_version
        tree.write(addon_xml_path, encoding='UTF-8', xml_declaration=True)
        print(f"Updated addon version: {version} -> {new_version}")
        return new_version
    return version

def are_dirs_identical(dir1, dir2):
    """Compare two directories recursively."""
    dcmp = filecmp.dircmp(dir1, dir2)
    if dcmp.left_only or dcmp.right_only or dcmp.diff_files or dcmp.funny_files:
        return False
    for sub_dcmp in dcmp.subdirs.values():
        if not are_dirs_identical(os.path.join(dir1, sub_dcmp.left), os.path.join(dir2, sub_dcmp.right)):
            return False
    return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python sync_upstream.py <path_to_upstream_repo> <path_to_addon>")
        sys.exit(1)
        
    upstream_path = sys.argv[1]
    addon_path = sys.argv[2]
    
    upstream_src = os.path.join(upstream_path, 'src')
    addon_dest = os.path.join(addon_path, 'resources', 'lib', 'flaresolverr')
    
    if not os.path.exists(upstream_src):
        print(f"Error: upstream source not found at {upstream_src}")
        sys.exit(1)
        
    # Check if there are differences
    if os.path.exists(addon_dest) and are_dirs_identical(upstream_src, addon_dest):
        print("No changes needed. Python logic is up-to-date with upstream.")
        sys.exit(2) # 2 means no changes
        
    print("Changes detected. Syncing upstream 'src' to 'resources/lib/flaresolverr'...")
    if os.path.exists(addon_dest):
        shutil.rmtree(addon_dest)
    shutil.copytree(upstream_src, addon_dest)
    
    update_addon_version(os.path.join(addon_path, 'addon.xml'))
    print("Successfully updated flaresolverr source with upstream.")
    sys.exit(0) # 0 means changes made
