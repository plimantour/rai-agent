
# Philippe Limantour - March 2024
# This file contains the functions to launch the draft of the RAI Impact Assessment for RAIS for Custom Solutions

import argparse
import os
import shutil
from prompts.prompts_engineering_llmlingua import update_rai_assessment_template, initialize_ai_models
from prompts.prompts_engineering_llmlingua import process_solution_description_security_analysis, process_solution_description_analysis
# from prompts_engineering import update_rai_assessment_template
from helpers.docs_utils import ExtractionError, extract_text_from_input
from pprint import pprint

def main():
    parser = argparse.ArgumentParser(description='Process input file.')
    parser.add_argument('-i', '--folderpath', required=True, type=str, help='Path to the input folder - containing the input file named solution_descrition.docx')
    parser.add_argument('-s', '--steps', action='store_true', default=False, help='Set to True to update and save docx step by step')
    parser.add_argument('-a', '--analysis', action='store_true', default=False, help='Set to True to analyze only the solution description')
    parser.add_argument('-r', '--risks', action='store_true', default=False, help='Set to True to analyze only the risks')
    parser.add_argument('-c', '--compress', action='store_true', default=False, help='Set to True for using llmlingua 2 prompt compression')
    parser.add_argument('-v', '--verbose', action='store_true', default=False, help='Set to True for verbose output')
    args = parser.parse_args()

    # Access the inputfile argument
    inputfolder = args.folderpath

    verbose = args.verbose

    initialize_ai_models()

    # Get text from the input file
    input_filepath = os.path.join(inputfolder, 'solution_description.docx')
    try:
        input_filename, text = extract_text_from_input(input_filepath)
    except ExtractionError as exc:
        print(f"Error reading input file {input_filepath}: {exc}")
        exit(1)

    if not text:
        print(f"Error reading input file {input_filepath}")
        exit(1)

    if args.analysis:
        answer, total_completion_cost = process_solution_description_analysis(text, verbose=verbose)
        print(answer)
        print(f"Total completion cost: {total_completion_cost}")
    elif args.risks:
        answer, total_completion_cost, rewritten_solution_description = process_solution_description_security_analysis(text, verbose=verbose)

        print(answer)
        print(f"\nTotal completion cost: {total_completion_cost}")

        print("*"*50)
        print("Rewritten solution description:\n")
        print(rewritten_solution_description)
    else:
        # # Copy the RAI template to the output folder
        masterfolder = os.path.join(os.getcwd(), 'rai-template')

        # Copy the RAI template to the output folder
        rai_master_filepath = os.path.join(masterfolder, 'RAI Impact Assessment for RAIS for Custom Solutions - MASTER.docx')
        rai_filepath = os.path.join(inputfolder, f'draftRAI_MsInternal.docx')
        try:
            shutil.copy(rai_master_filepath, rai_filepath)  # Copy the master RAI file template to the output folder
        except Exception as e:
            print(f"Error copying master rai file: {e}", "red")

        # Copy the public (customer approved) RAI template to the output folder
        rai_master_filepath = os.path.join(masterfolder, 'Microsoft-RAI-Impact-Assessment-Public-MASTER.docx')
        rai_public_filepath = os.path.join(inputfolder, f'draftRAI.docx')
        try:
            shutil.copy(rai_master_filepath, rai_public_filepath)  # Copy the public (customer approved) master RAI file template to the output folder
        except Exception as e:
            print(f"Error copying public master rai file: {e}", "red")

        if not os.path.exists(rai_filepath):
            print(f"File {rai_filepath} does not exist")
            exit(1)

        # Get the completion from Azure OpenAI to update the RAI template
        json = update_rai_assessment_template(
            solution_description=text,
            rai_filepath=rai_filepath,
            rai_public_filepath=rai_public_filepath,
            update_steps=args.steps,
            compress=args.compress,
            verbose=verbose)

        # if verbose:
        #     print('='*100)
        #     pprint(json)

if __name__ == '__main__':
    main()