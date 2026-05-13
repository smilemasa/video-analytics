from transformers import BlipProcessor, BlipForQuestionAnswering
from PIL import Image
import torch

try:
    processor = BlipProcessor.from_pretrained("Salesforce/blip-vqa-base")
    model = BlipForQuestionAnswering.from_pretrained("Salesforce/blip-vqa-base").to("cpu")
    print("BLIP loaded successfully.")
    
    # Dummy image
    image = Image.new('RGB', (224, 224), color = 'red')
    inputs = processor(image, "What color is this?", return_tensors="pt").to("cpu")
    out = model.generate(**inputs)
    print("BLIP output:", processor.decode(out[0], skip_special_tokens=True))
except Exception as e:
    print("Error:", e)
