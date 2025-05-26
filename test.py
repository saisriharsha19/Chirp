import torch
print("Torch version:", torch.__version__)
print("CUDA available:", torch.cuda.is_available())


from transformers import pipeline

# Load the ALBERT sentiment analysis pipeline
sentiment_pipeline = pipeline("sentiment-analysis", model="textattack/albert-base-v2-imdb")

def analyze_sentiment(text: str) -> str:
    result = sentiment_pipeline(text)[0]
    label = result['label'].lower()
    return label