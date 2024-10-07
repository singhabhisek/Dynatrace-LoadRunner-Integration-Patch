import os
import re
import sys

# Dynatrace function template with dynamic PC and LSN placeholders
dynatrace_function_template = '''\taddDynatraceHeaderTest("TSN={transaction_name};PC={step_name};SI=LoadRunner;LSN={lsn_name};");
'''

# Dynatrace function definition that will be added to globals.h
dynatrace_function_definition = '''
void addDynatraceHeaderTest(char* header){
    char* headerValue;
    int headerValueLength;
    int vuserid, scid;
    char *groupid, *timestamp;
    char* vuserstring=(char*) malloc(sizeof(char) * 10);
    char* ltnString=(char*) malloc(sizeof(char) * 10);

    if(lr_get_attrib_string("DynatraceLTN")!=NULL){
        strcpy(ltnString,lr_get_attrib_string("DynatraceLTN"));
    }
    lr_whoami(&vuserid, &groupid, &scid);
    itoa(vuserid,vuserstring,10);

    headerValueLength = strlen(header) + 4 + strlen(vuserstring) + 4 + strlen(ltnString) + 4;
    headerValue = (char*) malloc(sizeof(char) * headerValueLength);
    strcpy(headerValue, header);
    if(lr_get_attrib_string("DynatraceLTN")!=NULL){
        strcat(headerValue,"LTN=");
        strcat(ltnString,ltnString);
        strcat(headerValue,";");
    }
    strcat(headerValue,"VU=");
    strcat(headerValue,vuserstring);
    strcat(headerValue,";");

    web_add_header("X-dynaTrace-Test", headerValue);
    free(headerValue);
    free(vuserstring);
}
'''

# Excluded files array (Add your excluded files here)
excluded_files = ["excluded_file1.c", "excluded_file2.c"]  # You can add more files as needed


# Function to find the .usr file and return its name (without .usr extension)
def get_lsn_name(root_dir):
    for file in os.listdir(root_dir):
        if file.endswith('.usr'):
            return os.path.splitext(file)[0]
    return None


# Function to extract the step name from web_url, web_submit_data, or web_custom_request
def extract_step_name(line):
    match = re.search(r'\"([^\"]+)\"', line)
    if match:
        return match.group(1)
    return None


# Function to handle variable-based transaction names
def find_transaction_variable(line):
    # Match for variable assignment like abc = "04_Search_Products";
    tx_var_match = re.search(r'([a-zA-Z_]\w*)\s*=\s*\"([^\"]+)\";', line)
    if tx_var_match:
        return tx_var_match.group(1), tx_var_match.group(2)
    return None, None


# Function to process each .c file
def process_c_file(file_path, lsn_name, action):
    with open(file_path, 'r') as file:
        content = file.readlines()

    new_content = []
    transaction_name = None  # Keep track of the current transaction name
    tx_variables = {}  # Track variable-based transaction names
    inside_dynatrace_block = False  # Flag to track if we're inside a Dynatrace block to remove

    # Remove any existing Dynatrace headers first
    for line in content:
        # If the action is DELETE or INSERT, remove all existing addDynatraceHeaderTest calls
        if action in ['DELETE', 'INSERT'] and 'addDynatraceHeaderTest' in line:
            inside_dynatrace_block = True
            continue  # Skip this line (removes the call)
        elif inside_dynatrace_block and line.strip() == "":
            inside_dynatrace_block = False  # Finished skipping the Dynatrace block
            continue

        new_content.append(line)  # Add all other lines to the new content

    # If action is INSERT, add new Dynatrace headers after removing the old ones
    if action == 'INSERT':
        updated_content = []
        for line in new_content:

            # Handle dynamic transaction name with lr_eval_string and lr_param_sprintf
            dynamic_tx_name = extract_dynamic_transaction(line)
            if dynamic_tx_name:
                transaction_name = dynamic_tx_name

            # Handle case where a variable is assigned a transaction name
            tx_var, tx_name = find_transaction_variable(line)
            if tx_var:
                tx_variables[tx_var] = tx_name  # Store the variable and its value

            # Handle lr_start_transaction with a direct or variable transaction name
            transaction_match = re.search(r'lr_start_transaction\(([^)]+)\);', line)
            if transaction_match:
                transaction_value = transaction_match.group(1).strip()

                # Check if the transaction value is a variable and resolve it
                if transaction_value in tx_variables:
                    transaction_name = tx_variables[transaction_value]
                else:
                    # If it's not a variable, use the direct transaction name
                    transaction_name = transaction_value.strip('"')

            # Handle web_url, web_submit_data, or web_custom_request cases
            if 'web_url' in line or 'web_submit_data' in line or 'web_custom_request' in line:
                step_name = extract_step_name(line)  # Extract step name for PC
                if step_name:
                    # Use the resolved transaction name or default to NoTransaction
                    current_transaction = transaction_name if transaction_name else "NoTransaction"
                    # Add the Dynatrace header before the web request with transaction and step info
                    dynatrace_function = dynatrace_function_template.format(
                        transaction_name=current_transaction, step_name=step_name, lsn_name=lsn_name
                    )
                    updated_content.append(dynatrace_function)

            updated_content.append(line)  # Add the current line

        new_content = updated_content

    # Save the modified content back to the file
    with open(file_path, 'w') as file:
        file.writelines(new_content)


# Function to extract dynamic transaction names from lr_eval_string(lr_param_sprintf(...))
def extract_dynamic_transaction(line):
    # Match lr_eval_string(lr_param_sprintf("transaction_pattern_%d", i))
    dynamic_tx_match = re.search(r'lr_eval_string\s*\(\s*lr_param_sprintf\s*\(\s*"([^"]+)"', line)
    if dynamic_tx_match:
        return dynamic_tx_match.group(1)  # Return the dynamic transaction pattern
    return None

# Function to process the global.h file
def update_global_h(global_h_path, action):
    with open(global_h_path, 'r+') as file:
        content = file.read()

        # If the action is INSERT, ensure the function is present
        if action == 'INSERT':
            if 'addDynatraceHeaderTest' not in content:
                # Insert the function before the final #endif
                content = content.replace('#endif', dynatrace_function_definition + '\n#endif')
                file.seek(0)
                file.write(content)
                file.truncate()

        # If the action is DELETE, remove the function definition
        elif action == 'DELETE':
            content = re.sub(r'void addDynatraceHeaderTest.*?\}.*?#endif', '#endif', content, flags=re.DOTALL)
            file.seek(0)
            file.write(content)
            file.truncate()


# Main function to traverse the directory and process .c files
def traverse_directory(directory_path, action):
    for root, dirs, files in os.walk(directory_path):
        # Check if the folder contains a .usr file to get the LSN name
        lsn_name = get_lsn_name(root)

        if lsn_name:  # If an LSN name is found
            print(f'Found LSN: {lsn_name} in folder: {root}')
            for file in files:
                if file.endswith('.c'):
                    file_path = os.path.join(root, file)

                    # Skip if the file is in the excluded list
                    if file in excluded_files:
                        print(f'Skipping file (excluded): {file_path}')
                        continue

                    # Process each .c file
                    print(f'Processing file: {file_path}')
                    process_c_file(file_path, lsn_name, action)

                elif file == 'globals.h':
                    # Update globals.h with the function (either insert or delete)
                    global_h_path = os.path.join(root, file)
                    print(f'Updating globals.h: {global_h_path}')
                    update_global_h(global_h_path, action)


# Ensure proper usage
if len(sys.argv) < 3:
    print("Usage: python script.py <directory_path> <action: INSERT|DELETE>")
    sys.exit(1)

# Read arguments from command-line
directory_path = sys.argv[1]
action = sys.argv[2]

if action not in ['INSERT', 'DELETE']:
    print("Invalid action. Use 'INSERT' to add Dynatrace headers or 'DELETE' to remove them.")
    sys.exit(1)

# Execute the traversal based on action
traverse_directory(directory_path, action)
