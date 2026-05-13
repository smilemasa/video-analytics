from transformers import AutoProcessor, AutoModelForImageTextToText
from PIL import Image
import torch

try:
    print("Loading Qwen2.5-VL-3B-Instruct...")
    processor = AutoProcessor.from_pretrained("Qwen/Qwen2.5-VL-3B-Instruct")
    model = AutoModelForImageTextToText.from_pretrained("Qwen/Qwen2.5-VL-3B-Instruct", torch_dtype="auto", device_map="auto")
    print("Qwen2.5-VL-3B-Instruct loaded successfully.")

    # Dummy image
    image = Image.new('RGB', (224, 224), color='blue')
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": "What is in this image?"},
            ],
        }
    ]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt", padding=True).to(model.device)
    
    print("Running inference...")
    generated_ids = model.generate(**inputs, max_new_tokens=20)
    
    generated_ids_trimmed = [
        out_ids[len(in_ids):]
        for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]
    
    print("-" * 30)
    print("Output:", output_text)
    print("Qwen2.5-VL-3B-Instruct inference successful.")
except Exception as e:
    import traceback
    traceback.print_exc()
