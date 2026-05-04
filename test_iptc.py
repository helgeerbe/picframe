from PIL import Image
from PIL.IptcImagePlugin import getiptcinfo

def test_iptc(filepath):
    try:
        with Image.open(filepath) as img:
            iptc = getiptcinfo(img)
            if iptc:
                print(f"IPTC for {filepath}:")
                for k, v in iptc.items():
                    print(f"  {k}: {v}")
            else:
                print(f"No IPTC for {filepath}")
    except Exception as e:
        print(f"Error: {e}")

test_iptc("test/images/AlleExif.JPG")
