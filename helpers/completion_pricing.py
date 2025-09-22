# Philippe Limantour - March 2024
# This file contains the pricing for the different models and the function to calculate the cost of a completion based on the number of tokens used in the prompt.

from termcolor import colored

try:
    from termcolor import colored
except ImportError:
    def colored(x, *args, **kwargs):
        return x

model_pricing_euros = {
  "gpt-3.5-turbo-0125": {
    "Context": 16000,
    "NbTokens": 1000,
    "Input": 0.0005,
    "Output": 0.0014
  },
  "gpt-3.5-turbo-instruct": {
    "Context": 4000,
    "NbTokens": 1000,
    "Input": 0.0014,
    "Output": 0.002
  },
  "gpt-4-turbo": {
    "Context": 128000,
    "NbTokens": 1000,
    "Input": 0.010,
    "Output": 0.028
  },
  "gpt-4-turbo-vision": {
    "Context": 128000,
    "NbTokens": 1000,
    "Input": 0.010,
    "Output": 0.028
  },
  "gpt-4": {
    "Context": 8000,
    "NbTokens": 1000,
    "Input": 0.028,
    "Output": 0.056
  },
  "gpt-4o": {
    "Context": 128000,
    "NbTokens": 1000,
    "Input": 0.0047,
    "Output": 0.0139
  },
  "gpt-4o-mini": {
    "Context": 128000,
    "NbTokens": 1000,
    "Input": 0.00014277,
    "Output": 0.0005711
  },
  "o3-mini": {
    "Context": 200000,
    "NbTokens": 1000,
    "Input": 0.0010470,
    "Output": 0.004187884
  },
  "o1-mini": {
    "Context": 128000,
    "NbTokens": 1000,
    "Input": 0.0010470,
    "Output": 0.004187884
  },
  "gpt-4-32k": {
    "Context": 32000,
    "NbTokens": 1000,
    "Input": 0.056,
    "Output": 0.112
  },
  "azureai": {          # Mistral Large
    "Context": 32000,
    "NbTokens": 1000,
    "Input": 0.0074088,
    "Output": 0.0222264
}
}

# Function to calculate the cost of a completion based on the number of tokens used in the prompt
def get_completion_pricing_from_usage(model, nb_tokens_input_prompt, nb_tokens_output_prompt):
    model = model.lower()
    if model in model_pricing_euros.keys():
        model_cost = model_pricing_euros[model]
        model_cost_nbtokens = model_cost["NbTokens"]
        model_cost_input_pricing = model_cost["Input"]
        model_cost_output_pricing = model_cost["Output"]

        input_cost = (nb_tokens_input_prompt / model_cost_nbtokens) * model_cost_input_pricing
        output_cost = (nb_tokens_output_prompt / model_cost_nbtokens) * model_cost_output_pricing

        print(colored(f"Input Tokens: {nb_tokens_input_prompt} - Output Tokens: {nb_tokens_output_prompt}", "green"))

        return input_cost, output_cost
    else:
        print(colored(f"Model {model} not found in the pricing list", "red"))
        return 0, 0