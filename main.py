from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
#from fastapi.openapi.models import Info
from pydantic import BaseModel
import subprocess
import json
import os
import glob
import shutil
import zipfile
from datetime import datetime

# Get the full path to the directory containing the FastAPI script
script_dir = os.path.dirname(os.path.abspath(__file__))
out_dir = os.path.normpath(os.path.join(script_dir, "../out/"))
# Create the full path to the execute.sh script
execute_script_path = os.path.join(script_dir, "../bspm/execute.py")
app = FastAPI(
    openapi_tags=[
        {"name": "Execute", "description": "Run/Returns the status of execution by date: year-month-day"},
        {"name": "Retrieve Executions", "description": "Returns a list of executions completed by the user"},
        {"name": "Plot", "description": "Returns the plot image"},
        {"name": "Download", "description": "Returns the ZIP file of all outputs, including .png and .csv files."},
    ],
    title="BSPM API: 3D-Kinetic plasmasphere model",
    description="The BSPM is a 3D-Kinetic semiempirical model of the plasmasphere developed by the Solar Wind Division of the Royal Belgian Institute for Space Aeronomy.",
    version="1.0.0",
    root_path="/dc-bspm"
)

class ExecuteRequest(BaseModel):
    date: str


@app.post("/execute_v0", include_in_schema=False, summary="Execute the BSPM by passing the date.", description="Returns the status of execution by date: year-month-day", tags=["Execute"])
async def run_execute_script_v0(date: str = Query(..., description="Date in the format 'YYYY-MM-DD'"), rerun: bool = Query(False, description="Force the script to rerun even if the output files already exist.")):
    # Prepare the command to run execute.sh
    #command = f"{execute_script_path} --year {request.year} --month {request.month} --day {request.day}"
    #if request.executionid:
    #    command += f" --executionid {request.executionid}"
    #print("Command:", command)
    try:
        input_date = datetime.strptime(date, "%Y-%m-%d")
        year = input_date.year
        month = input_date.month
        day = input_date.day
        # Run the execute.sh script and capture its output
        command = f"{execute_script_path} --year {year} --month {month} --day {day}"
        if rerun:
            command += " --rerun true"
        # output = subprocess.check_output(command, shell=True, stderr=subprocess.STDOUT, universal_newlines=False, encoding="utf-8")

        os.system(f"python3 {command}")
        #print("Subprocess", output, "\n")
        #return output.strip()
        result = {"code":0, "message":"Execution submitted"}

        # Check the code in the result
        if result.get("code") == 0:
            # Success
            return result
        else:
            # Error
            return result
    except ValueError:
        # Handle invalid date format
        raise HTTPException(status_code=400, detail={"code": -1, "msg": "Invalid date format. Please provide a date in the format 'YYYY-MM-DD'"})
    except subprocess.CalledProcessError as e:
        # If the script exits with a non-zero status code, it's considered an error
        raise HTTPException(status_code=500, detail={"code": -1, "msg": "Error running execute.sh", "error_output": e.output})


@app.post("/execute", summary="Execute the BSPM by passing the date.", description="Returns the status of execution by date: year-month-day", tags=["Execute"])
async def run_execute_script(
    date: str = Query(..., description="Date in the format 'YYYY-MM-DD'"),
    rerun: bool = Query(False, description="Force the script to rerun even if the output files already exist.")
):
    try:
        # Validate the date format
        exec_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use 'YYYY-MM-DD'.")

    # Extract year, month, and day from the date
    year = exec_date.year
    month = exec_date.month
    day = exec_date.day
    executionid = f"{year:04d}-{month:02d}-{day:02d}"

    # Define the app name and script directory
    app_name = "BSPM_May2024.py"
    script_dir = "/home/ubuntu/DC-BSPM-API/DC-BSPM-MODEL"
    parent_dir = "/home/ubuntu/DC-BSPM-API"
    
    # Set the environment variable
    os.environ['LD_LIBRARY_PATH'] = f"/home/ubuntu/DC-BSPM-API/DC-BSPM-MODEL/Libs/iri2016"

    # Define the output folder path
    output_folder = f"{parent_dir}/out/bspm/ubuntu/{executionid}"
    python_command = f"IRI0_IRILIB64PATH=irilib64.so LD_PRELOAD=iri0.so python3.9 {script_dir}/{app_name} --year {year} --month {month} --day {day} --executionid {executionid}"

    # Check if rerun is provided, if true, remove the output folder
    if rerun and os.path.isdir(output_folder):
        subprocess.run(['rm', '-rf', output_folder])

    # Check if the output folder exists; create it if it doesn't
    if not os.path.isdir(output_folder):
        os.makedirs(output_folder)
        with open(f"{output_folder}/app.log", 'w') as log_file:
            subprocess.Popen(python_command, shell=True, stdout=log_file, stderr=subprocess.STDOUT)
        return {"code": 0, "msg": f"Started a new execution of {app_name} by date {executionid}", "date": executionid, "status": "start"}
    else:
        if subprocess.run(['pgrep', '-f', f"{app_name}.*--executionid {executionid}"]).returncode == 0:
            return {"code": 0, "msg": f"App {app_name} on date {executionid} is already running.", "date": executionid, "status": "progressing"}
        else:
            return {"code": 1, "msg": f"App {app_name} on date {executionid} is completed.", "date": executionid, "status": "completed"}


@app.get("/executions", summary="Retrieve a list of user executions.", description="Returns a list of executions completed by the user.",tags=["Retrieve Executions"])
async def get_user_executions():
    # Get the current user's username
    username = "ubuntu"

    # Define the directory to list folders in
    user_directory = f"{out_dir}/bspm/{username}/"
    if os.path.exists(user_directory) and os.path.isdir(user_directory):
        folder_list = [f for f in os.listdir(user_directory) if os.path.isdir(os.path.join(user_directory, f))]
        # Sort the folders by date in descending order
        folder_list.sort(reverse=True)
        execution_list = {}
        execution_list["progressing"] = []
        execution_list["completed"] = []

        for folder in folder_list:
            folder_path = os.path.join(user_directory, folder)
            # Check the last 2 lines of the log file to store in the log variable, and check if the execution is completed. The log file is stored in the folder with name 'app.log'
            log_file = os.path.join(folder_path, "app.log")
            status = "progressing"
            log = None
            execution_time = None
            total_time = 24
            if os.path.exists(log_file):
                with open(log_file, "r") as f:
                    log = f.readlines()[-3:]
                    # Last 3 lines of the log file if the execution is completed:
                    # BSPM COMPLETED\n
                    # 2050.457169532776  seconds\n
                    # Loop all lines in the log variable to check if the execution is completed
                    for line in log:
                        if "BSPM COMPLETED" in line:
                            status = "completed"
                        if "seconds" in line:
                            execution_time = float(line.split(' ')[0])

            # Count the number of .png files in the folder
            png_files = [f for f in os.listdir(folder_path) if f.endswith(".png")]
            num_png_files = len(png_files)
            # Determine the status based on the number of .png files
            if status == "completed":
                total_time = num_png_files
            else:
                status = "completed" if num_png_files == total_time else "progressing"
            # Add execution information to the list
            execution_info = {
                "date": folder,
                "status": status,
                "progress": f"{num_png_files}/{total_time}",
            }
            if status == "completed":
                execution_info["execution_time"] = execution_time
                execution_list["completed"].append(execution_info)
            else:
                execution_info["log"] = log
                execution_list["progressing"].append(execution_info)
        # Convert the folder list to JSON format
        user_directories = {"user": username, "executions": execution_list}
        response = JSONResponse(content=user_directories)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "Mon, 01 Jan 2000 00:00:00 GMT"

        return response
    else:
        return {"error": f"The directory '{user_directory}' does not exist or / is not a directory."}


@app.get("/plot", summary="Plot the output image by passing the execution date and hour.", description="Returns the plot image.",tags=["Plot"])
async def get_plot_image(
    date: str,
    hour: int
):
    # Get the current user's username
    username = "ubuntu"
    # Construct the filename pattern based on the input parameters
    filename_pattern = f"*_{date}_{hour:02d}h*.png"
    print(filename_pattern)
    # Use glob to search for files matching the pattern
    matching_files = glob.glob(os.path.join(f"{out_dir}/bspm/{username}/{date}/", filename_pattern))

    # Check if any matching files were found
    if matching_files:
        # Take the first matching file (you can handle multiple matches if needed)
        image_path = matching_files[0]

        # Return the image as a FileResponse
        return FileResponse(image_path, media_type="image/png")
    else:
        # Get the list of files in the directory
        files = os.listdir(f"{out_dir}/bspm/{username}/{date}/")
        # Return the list of files with extension .png
        files = [f for f in files if f.endswith(".png")]
        return {"error": f"Image not found for the specified date and hour. The execution for {date} is in progress.", "available_plots": files, "status": "progressing"}


@app.get("/download", summary="Download all the outputs by passing the execution date.", description="Returns the ZIP file of all outputs, including .png and .csv files.",tags=["Download"])
async def download_execution_data(date: str):
    # Get the current user's username
    username = "ubuntu"
    # Construct the path to the execution folder
    execution_path = os.path.join(f"{out_dir}/bspm/{username}/", date)

    # Check if the execution folder exists
    if os.path.exists(execution_path) and os.path.isdir(execution_path):

        png_files = [f for f in os.listdir(execution_path) if f.endswith(".png")]
        num_png_files = len(png_files)
        # Determine the status based on the number of .png files
        status = "completed" if num_png_files == 24 else "progressing"

        if status == "progressing":
            return {"error": f"Execution for date '{date}' is in progress.", "status": status, "progress": f"{num_png_files}/24"}

        if status == "completed":
            # Create a temporary zip file
            zip_filename = f"{date}.zip"
            zip_filepath = os.path.join(f"{out_dir}/bspm/{username}/", zip_filename)
            with zipfile.ZipFile(zip_filepath, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Recursively add all files and subdirectories to the zip file
                for root, dirs, files in os.walk(execution_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, execution_path)
                        zipf.write(file_path, arcname=arcname)
            # Return the zip file as a FileResponse
            return FileResponse(zip_filepath, media_type="application/octet-stream", headers={"Content-Disposition": f"attachment; filename={zip_filename}"})
    else:
        # Return a 404 Not Found response if the execution folder does not exist
        return {"error": f"Execution folder for date '{date}' not found."}
