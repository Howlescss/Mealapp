import google.generativeai as genai

genai.configure(api_key="AQ.Ab8RN6Kl5RQuA__Y8sjmzNbHhnQNcyylIdfWHqg509OXn9XuZw")

print("Modelele disponibile pentru tine sunt:")
for m in genai.list_models():
    if 'generateContent' in m.supported_generation_methods:
        print(m.name)