import os  # Importing the os module for file and directory operations
import re  # Importing the re module for regular expressions
import sys  # Importing sys to handle command-line arguments

# Template for adding the Dynatrace header function in LoadRunner scripts
dynatrace_function_template = '\taddDynatraceHeaderTest("{tsn}PC={step_name};SI=LoadRunner;LSN={lsn_name};");\n'

# Definition of the Dynatrace function to be added to `global.h`
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
        strcat(headerValue,ltnString);
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

# List of files to be excluded from processing
excluded_files = ["excluded_file1.c", "excluded_file2.c"]

# Function to get the LSN (LoadRunner Script Name) from a `.usr` file
def get_lsn_name(root_dir):
    for file in os.listdir(root_dir):  # Loop through files in the given directory
        if file.endswith('.usr'):  # Check if the file has a `.usr` extension
            return os.path.splitext(file)[0]  # Extract the filename without extension
    return "UnknownLSN"  # Return a default name if no `.usr` file is found

# Function to extract the step name from a given line index in the script
def extract_step_name(lines, index):
    step_name_match = re.search(r'"([^"]+)"', lines[index])  # Search for a quoted string
    if step_name_match:
        return step_name_match.group(1)  # Return the step name if found
    
    # Handle multi-line step names
    for i in range(index + 1, len(lines)):  # Continue checking next lines
        step_name_match = re.search(r'"([^"]+)"', lines[i])
        if step_name_match:
            return step_name_match.group(1)
        if ';' in lines[i]:  # Stop if the statement ends without a match
            break
    
    return "UnknownStep"  # Return a default value if no step name is found

# Function to check if a line is commented
def is_commented(line):
    return line.strip().startswith("//") or "/*" in line or "*/" in line  # Check for comment markers

# Function to process a `.c` file and either insert or delete Dynatrace headers
def process_c_file(file_path, lsn_name, action):
    with open(file_path, 'r') as file:
        content = file.readlines()  # Read all lines from the file

    new_content = []  # List to store modified file content
    transaction_name = None  # Store current transaction name
    inside_comment = False  # Track whether inside a block comment

    for i, line in enumerate(content):  # Loop through each line in the file
        if '/*' in line:
            inside_comment = True  # Start of a multi-line comment block
        if '*/' in line:
            inside_comment = False  # End of a multi-line comment block
            new_content.append(line)
            continue
        
        if inside_comment or is_commented(line):  # Skip commented lines
            new_content.append(line)
            continue

        # Check if this line starts a LoadRunner transaction
        transaction_match = re.search(r'lr_start_transaction\("([^"]+)"\);', line)
        if transaction_match:
            transaction_name = transaction_match.group(1)  # Store the transaction name

        # If inserting, add Dynatrace headers before web_* calls
        if action == "INSERT" and any(keyword in line for keyword in ['web_url', 'web_submit_data', 'web_custom_request']):
            step_name = extract_step_name(content, i)  # Get the step name
            tsn_part = f"TSN={transaction_name};" if transaction_name else ""  # Include TSN if available
            dynatrace_header = dynatrace_function_template.format(tsn=tsn_part, step_name=step_name, lsn_name=lsn_name)
            new_content.append(dynatrace_header)  # Insert the Dynatrace header
        
        # If deleting, remove existing Dynatrace header calls
        if action == "DELETE" and 'addDynatraceHeaderTest' in line:
            continue  # Skip this line (remove it)

        new_content.append(line)  # Add the (possibly modified) line to new content
        
        # Check if this line ends a transaction
        if re.search(r'lr_end_transaction\("([^"]+)"', line):
            transaction_name = None  # Reset the transaction name

    with open(file_path, 'w') as file:
        file.writelines(new_content)  # Write the modified content back to the file

# Function to update the `global.h` file (add or remove the function definition)
def update_global_h(global_h_path, action):
    with open(global_h_path, 'r+') as file:
        content = file.read()  # Read the entire file content

        if action == 'INSERT':  # If inserting the function definition
            if 'addDynatraceHeaderTest' not in content:  # Check if not already present
                content = content.replace('#endif', dynatrace_function_definition + '\n#endif')  # Insert before #endif
                file.seek(0)
                file.write(content)
                file.truncate()

        elif action == 'DELETE':  # If removing the function definition
            content = re.sub(r'void addDynatraceHeaderTest.*?\}.*?#endif', '#endif', content, flags=re.DOTALL)  # Remove function block
            file.seek(0)
            file.write(content)
            file.truncate()

# Function to process all `.c` files in a directory (only top-level files)
def process_directory(directory_path, action):
    lsn_name = get_lsn_name(directory_path)  # Get the LoadRunner Script Name
    print(f'Processing LSN: {lsn_name} in folder: {directory_path}')
    
    for file in os.listdir(directory_path):  # Loop through files in the directory
        file_path = os.path.join(directory_path, file)

        # Process only `.c` files at the top level
        if os.path.isfile(file_path) and file.endswith('.c') and file not in excluded_files:
            print(f'Processing {action}: {file_path}')
            process_c_file(file_path, lsn_name, action)  # Modify the file accordingly

# Main script execution starts here
if len(sys.argv) < 3:
    print("Usage: python patch_loadrunner.py <directory_path> <INSERT|DELETE>")
    sys.exit(1)  # Exit if not enough arguments provided

directory_path = sys.argv[1]  # Get directory path from command-line arguments
action = sys.argv[2].upper()  # Get action (INSERT/DELETE) and convert to uppercase

if action not in ["INSERT", "DELETE"]:  # Validate action
    print("Invalid action. Use INSERT or DELETE.")
    sys.exit(1)

# Update the global.h file if it exists
global_h_path = os.path.join(directory_path, "globals.h")
if os.path.exists(global_h_path):
    print(f'Updating {action} in globals.h...')
    update_global_h(global_h_path, action)
else:
    print(f"globals.h not found in {directory_path}, skipping...")

# Process all `.c` files in the directory
process_directory(directory_path, action)
