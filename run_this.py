import subprocess


def generate_datasets():
    datasets = ['dataset1', 'dataset2', 'dataset3']

    for dataset in datasets:
        print(f"Generating {dataset}...")
        result = subprocess.run(['python3', 'generate_datasets.py', dataset], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"Successfully generated {dataset}.")
        else:
            print(f"Error generating {dataset}: {result.stderr}")

    print("All datasets have been generated.")
    print(f"Generated files: {', '.join(datasets)}")


if __name__ == '__main__':
    generate_datasets()