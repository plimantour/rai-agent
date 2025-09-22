
# Philippe Limantour - March 2024
# This file contains a function to delete a cache entry

# 530201d9c194e988965b56a8b6542ca1

import argparse
import os

from helpers.cache_completions import delete_cache_entry

def main():
    parser = argparse.ArgumentParser(description='Delete a cache entry from the cache')
    parser.add_argument('-k', '--key', required=True, type=str, help='key to be deleted from the cache')
    args = parser.parse_args()

    key = args.key
    key_split = key.split(',')
    key_list = [key.strip() for key in key_split]

    # Delete the cache entry(ies)
    delete_cache_entry(key_list)

if __name__ == '__main__':
    main()