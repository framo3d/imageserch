import sys
sys.path.append('/home/morteza/services')
import argparse
from glob import glob
from random import randint
from string import digits, ascii_letters
from threading import Thread, Lock, Event, Semaphore
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep, time as time_monotonic
from timeit import default_timer
import os
import cv2
import numpy as np
from flask import Flask, request, jsonify
import traceback
import queue
import uuid
import psutil
import threading
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from datetime import datetime
import heapq
import resource

from main.models import *
from main.colordescriptor import ColorDescriptor

UPLOAD_FOLDER = 'webservice/uploads'
DEBUG_SEARCH = True
MAX_CPU_PERCENT_PER_REQUEST = 30  # Maximum CPU usage per request
MAX_TOTAL_CPU_PERCENT = 50  # Maximum total CPU usage
MAX_CONCURRENT_REQUESTS = 1  # Maximum number of concurrent search requests
SEARCH_TIMEOUT = 120  # Maximum search time in seconds
MIN_RESULTS = 5  # Minimum number of results to return
TOP_N = 100  # فقط 100 نتیجه برتر را نگه دار

@dataclass
class SearchTask:
    task_id: str
    image_path: str
    filter_ids: List[int]
    start_time: float
    status: str = "queued"
    results: List[Tuple[str, float]] = None
    error_message: Optional[str] = None
    completion_event: Event = None
    
    def __post_init__(self):
        self.results = []
        self.completion_event = Event()

class CPUMonitor:
    def __init__(self, max_total_cpu=MAX_TOTAL_CPU_PERCENT, check_interval=0.5):
        self.max_total_cpu = max_total_cpu
        self.check_interval = check_interval
        self.last_check_time = 0
        self.last_cpu_percent = 0
        self.lock = Lock()
        
    def get_current_cpu_usage(self) -> float:
        current_time = time_monotonic()
        with self.lock:
            if current_time - self.last_check_time >= self.check_interval:
                self.last_cpu_percent = psutil.cpu_percent(interval=None)
                self.last_check_time = current_time
            return self.last_cpu_percent
            
    def should_throttle(self, request_cpu_target) -> Tuple[bool, float]:
        current_cpu = self.get_current_cpu_usage()
        if current_cpu > self.max_total_cpu:
            sleep_time = (current_cpu - self.max_total_cpu) / 100.0
            return True, sleep_time
        elif current_cpu + request_cpu_target > self.max_total_cpu:
            sleep_time = (current_cpu + request_cpu_target - self.max_total_cpu) / 100.0
            return True, sleep_time
        return False, 0.0

class SearchManager:
    def __init__(self, max_workers=1):
        self.tasks: Dict[str, SearchTask] = {}
        self.tasks_lock = Lock()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.process = psutil.Process()
        self._stop_event = Event()
        self.request_semaphore = Semaphore(MAX_CONCURRENT_REQUESTS)
        self.processing_lock = Lock()  # New lock for processing state

    def create_task(self, image_path: str, filter_ids: List[int]) -> str:
        task_id = str(uuid.uuid4())
        task = SearchTask(
            task_id=task_id,
            image_path=image_path,
            filter_ids=filter_ids,
            start_time=time_monotonic()
        )
        with self.tasks_lock:
            self.tasks[task_id] = task
        return task_id

    def get_task_status(self, task_id: str) -> Optional[dict]:
        with self.tasks_lock:
            task = self.tasks.get(task_id)
            if not task:
                return None
            
            result = {
                "status": task.status,
                "timestamp": task.start_time
            }
            
            if task.status == "completed":
                result["results"] = task.results
            elif task.status == "error":
                result["error_message"] = task.error_message
                
            return result

    def wait_for_completion(self, task_id: str, timeout: float) -> bool:
        """Wait for task completion with verification"""
        start_time = time_monotonic()
        with self.tasks_lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
                
        # Wait for completion event
        completed = task.completion_event.wait(timeout=timeout)
        if not completed:
            return False
            
        # Verify task status
        with self.tasks_lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            return task.status == "completed"

    def _limit_cpu_usage(self, request_cpu_target=MAX_CPU_PERCENT_PER_REQUEST):
        pass

    def process_stack_chunk(self, task: SearchTask, stack_chunk: List[tuple], 
                          query_description: tuple) -> List[tuple]:
        """Process a chunk of the stack with CPU usage control"""
        chunk_results = []
        items_processed = 0
        chunk_start_time = time_monotonic()
        total_items = len(stack_chunk)
        
        for stack_item_id_encoded, stack_item_data in stack_chunk:
            try:
                # CPU control with dynamic adjustment
                if items_processed % 10 == 0:  # Check every 10 items
                    self._limit_cpu_usage()
                    # Adjust processing speed based on time spent
                    elapsed = time_monotonic() - chunk_start_time
                    if elapsed > 0:
                        items_per_second = items_processed / elapsed
                        if items_per_second > 1000:  # If processing too fast
                            sleep(0.001)  # Small delay to reduce CPU usage
                
                decoded_id = decode(stack_item_id_encoded)
                if task.filter_ids and decoded_id not in task.filter_ids:
                    continue

                distance = compare_features(query_description, stack_item_data)
                if distance < 0.9:  # برای تست، مقدار را بالا ببرید
                    chunk_results.append((stack_item_id_encoded, distance))
                    
                items_processed += 1
                if DEBUG_SEARCH and items_processed < 20:
                    print(f"ID: {decoded_id}, Distance: {distance}")
                    
            except Exception as e:
                if DEBUG_SEARCH:
                    print(f"Error processing stack item {stack_item_id_encoded}: {e}")
                continue
                
        return chunk_results

    def search_worker(self, task: SearchTask):
        """Main search worker that processes the entire stack"""
        try:
            with self.processing_lock:  # Ensure exclusive processing
                if not os.path.exists(task.image_path):
                    raise FileNotFoundError(f"Image file not found: {task.image_path}")
                    
                image = cv2.imread(task.image_path)
                if image is None:
                    raise ValueError("Could not read image file")

                query_description = cd.describe(image)
                
                # Calculate optimal chunk size based on total stack size
                total_stack_size = len(stack)
                cpu_count = psutil.cpu_count() or 4
                optimal_chunks = cpu_count * 2
                chunk_size = max(100, total_stack_size // optimal_chunks)
                stack_chunks = [stack[i:i + chunk_size] for i in range(0, total_stack_size, chunk_size)]
                
                if DEBUG_SEARCH:
                    print(f"Task {task.task_id}: Processing {len(stack_chunks)} chunks, total items: {total_stack_size}")
                
                all_results = []
                completed_chunks = 0
                total_chunks = len(stack_chunks)
                
                # Process each chunk sequentially to ensure complete processing
                for chunk_index, chunk in enumerate(stack_chunks):
                    try:
                        chunk_results = self.process_stack_chunk(task, chunk, query_description)
                        all_results.extend(chunk_results)
                        completed_chunks += 1
                        if DEBUG_SEARCH:
                            print(f"Task {task.task_id}: Completed chunk {completed_chunks}/{total_chunks}")
                    except Exception as e:
                        if DEBUG_SEARCH:
                            print(f"Error processing chunk {chunk_index}: {e}")
                        continue

                # Only set results and complete status after ALL chunks are processed
                if completed_chunks == total_chunks:
                    all_results.sort(key=lambda x: x[1])
                    task.results = all_results[:TOP_N] if all_results else []
                    task.status = "completed"
                    if DEBUG_SEARCH:
                        print(f"Task {task.task_id}: Completed successfully, found {len(all_results)} matches")
                else:
                    task.status = "error"
                    task.error_message = f"Incomplete processing: only {completed_chunks}/{total_chunks} chunks completed"
                
        except Exception as e:
            task.status = "error"
            task.error_message = str(e)
            if DEBUG_SEARCH:
                print(f"Search task {task.task_id} failed: {e}")
                traceback.print_exc()
        finally:
            try:
                if os.path.exists(task.image_path):
                    os.remove(task.image_path)
            except Exception as e:
                print(f"Error cleaning up temp file: {e}")
            
            task.completion_event.set()

    def start_search(self, task_id: str):
        """Start processing a search task"""
        with self.tasks_lock:
            task = self.tasks.get(task_id)
            if not task:
                return
            
            task.status = "processing"
            self.executor.submit(self.search_worker, task)

    def cleanup_old_tasks(self, max_age: float = 3600):
        """Clean up completed tasks older than max_age seconds"""
        current_time = time_monotonic()
        with self.tasks_lock:
            for task_id in list(self.tasks.keys()):
                task = self.tasks[task_id]
                if current_time - task.start_time > max_age:
                    del self.tasks[task_id]

    def shutdown(self):
        """Shutdown the search manager"""
        self._stop_event.set()
        self.executor.shutdown(wait=True)

# Initialize Flask and other globals
app = Flask(__name__)
cd = ColorDescriptor((8, 12, 3))
BASE62 = digits + ascii_letters

# Parse arguments and load stack
ap = argparse.ArgumentParser()
ap.add_argument("-s", "--stack", required=True, help="The number of service-stack n>=0")
args = vars(ap.parse_args())

step = int(args["stack"])
port = 1950 + step

# Initialize SearchManager
search_manager = SearchManager(max_workers=1)

# Load stack files (existing code remains the same)
stack_files = sorted(glob(r"main/stacks/stack*.npz"), 
                    key=lambda i: int(os.path.basename(i).replace("stack", "").split(".")[0]))

if not stack_files:
    alt_path = "/home/morteza/services/main/compressed_stacks"
    if os.path.exists(alt_path):
        stack_files = sorted(glob(os.path.join(alt_path, "stack*.npz")),
                             key=lambda i: int(os.path.basename(i).replace("stack", "").split(".")[0]))

if stack_files:
    print(f"Found {len(stack_files)} stack files")
    if step < len(stack_files):
        stack_fn = stack_files[step]
    else:
        print(f"ERROR: Stack {step} not found. Available stacks: {len(stack_files)}")
        stack_fn = stack_files[0] if stack_files else None
else:
    print("ERROR: No stack files found")
    stack_fn = None
    stack = []

if stack_fn:
    print(f"Loading stack: {stack_fn}")
    with np.load(stack_fn, allow_pickle=True) as sel_stack:
        try:
            stack_dict = dict(sel_stack['arr_0'].item())
            stack = list(stack_dict.items())
            print(f"Stack loaded as dictionary with {len(stack)} items")
        except:
            try:
                stack = list(sel_stack['arr_0'].T.tolist().items())
                print(f"Stack loaded as array with {len(stack)} items")
            except:
                print(f"ERROR: Could not load stack. Trying alternative method.")
                try:
                    stack_data = sel_stack['arr_0']
                    stack = []
                    for i in range(len(stack_data)):
                        try: stack.append(stack_data[i])
                        except: pass
                    print(f"Stack loaded using direct method with {len(stack)} items")
                except Exception as e:
                    print(f"ERROR: Failed to load stack: {e}")
                    stack = []
else:
    stack = []

def decode(string, alphabet=BASE62) -> int:
    base, strlen = len(alphabet), len(string)
    return sum(alphabet.index(d) * (base ** (strlen - (i + 1))) for i, d in enumerate(string))

print("Stack loading complete.")

def compare_features(query_features_desc_tuple, stored_item_data):
    """
    Compares query image features with stored image features.
    Handles different formats of stored_item_data from the stack.
    query_features_desc_tuple is always (query_features, query_hash, query_local_desc).
    stored_item_data can be:
        1. New format: (features, hash, local_desc)
        2. Old format: (features, hash) - local_desc will be None
        3. Very old format: features_array - hash and local_desc will be None (less likely but good to handle)
        4. String (potentially an ID or filename if stack format is unexpected) - skip these.
    Returns a distance (1.0 - similarity), where lower is better.
    """
    q_features, q_hash, q_local_desc = query_features_desc_tuple

    stored_features, stored_hash, stored_local_desc = None, None, None

    if isinstance(stored_item_data, tuple):
        if len(stored_item_data) == 3:
            stored_features, stored_hash, stored_local_desc = stored_item_data
        elif len(stored_item_data) == 2:
            stored_features, stored_hash = stored_item_data
            # stored_local_desc remains None, which is fine for cd.compare
        elif len(stored_item_data) == 1 and isinstance(stored_item_data[0], np.ndarray):
             stored_features = stored_item_data[0]
             # stored_hash and stored_local_desc remain None
        else: # Unknown tuple format
            # print(f"Warning: Unknown tuple format in stored_item_data: {stored_item_data}")
            return float('inf') # Max distance for uncomparable items
    elif isinstance(stored_item_data, np.ndarray):
        stored_features = stored_item_data
        # stored_hash and stored_local_desc remain None
    else:
        # If stored_item_data is not a tuple or ndarray (e.g. just an ID or string), it cannot be compared directly.
        # This might happen if stack loading resulted in mixed types unexpectedly.
        # print(f"Warning: Uncomparable stored_item_data type: {type(stored_item_data)}")
        return float('inf') # Max distance for uncomparable items

    try:
        # Ensure all parts are correctly typed before passing to compare
        # cd.compare expects features, hash, desc for both. Pass None if not available.
        
        # Convert to np.float32 if they are numpy arrays
        if isinstance(stored_features, np.ndarray):
            stored_features = stored_features.astype(np.float32)
        if isinstance(q_features, np.ndarray):
            q_features = q_features.astype(np.float32)
        
        if isinstance(stored_local_desc, np.ndarray) and stored_local_desc.size > 0:
            stored_local_desc = stored_local_desc.astype(np.float32)
        else: # Ensure it's None if not a valid ndarray (e.g. empty or zero placeholder from old describe)
            stored_local_desc = None 
            
        if isinstance(q_local_desc, np.ndarray) and q_local_desc.size > 0:
            q_local_desc = q_local_desc.astype(np.float32)
        else:
            q_local_desc = None

        similarity = cd.compare(stored_features, stored_hash, stored_local_desc, 
                                q_features, q_hash, q_local_desc)
        return 1.0 - similarity  # Convert similarity (0-1) to distance (0-1)
    except TypeError as te:
        # This can happen if, for example, a hash is None and int() fails in cd.compare
        # Or if features are not in expected format (e.g. list instead of ndarray inside tuple)
        if DEBUG_SEARCH:
            print(f"TypeError in cd.compare: {te}. Query: ({type(q_features)}, {type(q_hash)}, {type(q_local_desc)}), Stored: ({type(stored_features)}, {type(stored_hash)}, {type(stored_local_desc)})")
        return float('inf') # Max distance
    except Exception as e:
        if DEBUG_SEARCH:
            print(f"Error in ColorDescriptor.compare or feature preparation: {e}. Falling back to simple chi2 if possible.")
        # Fallback to chi2_distance if only features are available and are numpy arrays
        if isinstance(q_features, np.ndarray) and isinstance(stored_features, np.ndarray):
            try:
                return chi2_distance(stored_features, q_features)
            except Exception as chi_e:
                if DEBUG_SEARCH:
                    print(f"Fallback chi2_distance also failed: {chi_e}")
                return float('inf')
        return float('inf') # Max distance if fallback not possible

def chi2_distance(histA, histB, eps=1e-10):
    histA = np.array(histA, dtype=np.float32)
    histB = np.array(histB, dtype=np.float32)
    return 0.5 * np.sum(((histA - histB) ** 2) / (histA + histB + eps))

@app.route("/process", methods=['POST'])
def legacy_process_adapter():
    """Legacy endpoint adapter with guaranteed completion"""
    if DEBUG_SEARCH:
        print(f"Legacy /process endpoint hit by: {request.remote_addr}")

    try:
        # Handle file upload
        img_path = None
        if 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return jsonify({"msg": "error", "error": "No selected file"}), 400
            
            filename = os.path.basename(file.filename)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            img_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            file.save(img_path)
        elif request.values.get("fp"):
            original_fp = request.values.get("fp")
            if not os.path.exists(original_fp):
                return jsonify({"msg": "error", "error": f"File not found: {original_fp}"}), 400
            
            filename = os.path.basename(original_fp)
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            img_path = os.path.join(UPLOAD_FOLDER, unique_filename)
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            import shutil
            shutil.copy2(original_fp, img_path)
        else:
            return jsonify({"msg": "error", "error": "No file provided"}), 400

        # Get filter IDs if any
        filter_ids = []
        if request.values.get('tag') or request.values.get('word'):
            were_c = []
            if request.values.get('tag'):
                were_c.append(Images.tags.any(name=request.values.get('tag')))
            if request.values.get('word'):
                were_c.append(Info.title.like(f"%{request.values.get('word')}%"))
            with Images().__ss__() as ss:
                query_db = ss.query(Images.id).filter(Images.stack_num == step).join(Info).where(*were_c).all()
                filter_ids = [img.id for img in query_db]

        # Create and start search task
        task_id = search_manager.create_task(img_path, filter_ids)
        search_manager.start_search(task_id)

        # Wait for completion and verify
        if search_manager.wait_for_completion(task_id, SEARCH_TIMEOUT):
            task_status = search_manager.get_task_status(task_id)
            if task_status["status"] == "completed":
                results = task_status.get("results", [])
                if results:  # If we have results, return them
                    return jsonify(results)
                else:  # If no results found, return empty list with 200 status
                    return jsonify([])
            else:
                error_msg = task_status.get("error_message", "Search completed but no results found")
                return jsonify({"msg": "error", "error": error_msg}), 500
        else:
            return jsonify({"msg": "error", "error": "Search timed out or failed to complete"}), 408

    except Exception as e:
        print(f"Error in legacy_process_adapter: {e}")
        traceback.print_exc()
        if img_path and os.path.exists(img_path):
            try:
                os.remove(img_path)
            except:
                pass
        return jsonify({"msg": "error", "error": str(e)}), 500

@app.route("/search/submit", methods=['POST'])
def submit_search():
    """Modern endpoint for submitting searches"""
    if 'file' not in request.files:
        return jsonify({"msg": "error", "error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"msg": "error", "error": "No selected file"}), 400

    try:
        # Save uploaded file
        filename = os.path.basename(file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        img_path = os.path.join(UPLOAD_FOLDER, unique_filename)
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        file.save(img_path)

        # Get filter IDs
        filter_ids = []
        if request.values.get('tag') or request.values.get('word'):
            were_c = []
            if request.values.get('tag'):
                were_c.append(Images.tags.any(name=request.values.get('tag')))
            if request.values.get('word'):
                were_c.append(Info.title.like(f"%{request.values.get('word')}%"))
            with Images().__ss__() as ss:
                query_db = ss.query(Images.id).filter(Images.stack_num == step).join(Info).where(*were_c).all()
                filter_ids = [img.id for img in query_db]

        # Create and start search task
        task_id = search_manager.create_task(img_path, filter_ids)
        search_manager.start_search(task_id)
        
        return jsonify({
            "msg": "success",
            "task_id": task_id,
            "status": "processing"
        }), 202

    except Exception as e:
        print(f"Error in submit_search: {e}")
        traceback.print_exc()
        if img_path and os.path.exists(img_path):
            try:
                os.remove(img_path)
            except:
                pass
        return jsonify({"msg": "error", "error": str(e)}), 500

@app.route("/search/status/<task_id>", methods=['GET'])
def get_search_status(task_id):
    """Get status of a search task"""
    task_status = search_manager.get_task_status(task_id)
    if task_status is None:
        return jsonify({"msg": "error", "error": "Task not found"}), 404
    return jsonify(task_status)

@app.route("/start", methods=['GET'])
def start_legacy_processing_endpoint():
    """Health check endpoint"""
    return jsonify({
        "status": "Server is running with controlled processing",
        "stack_loaded": step if stack else -1,
        "max_cpu_percent": MAX_CPU_PERCENT_PER_REQUEST,
        "search_timeout": SEARCH_TIMEOUT
    })

def cleanup_thread():
    """Background thread for cleaning up old tasks"""
    while not search_manager._stop_event.is_set():
        try:
            search_manager.cleanup_old_tasks()
        except Exception as e:
            print(f"Error in cleanup thread: {e}")
        sleep(300)  # Run every 5 minutes

if __name__ == "__main__":
    # Start cleanup thread
    cleanup_thread = Thread(target=cleanup_thread, daemon=True)
    cleanup_thread.start()
    
    # Start Flask server
    print(f"Starting Flask server on port {port}...")
    app.run(host="127.0.0.1", port=port, threaded=True)
    
    # Cleanup on shutdown
    search_manager.shutdown()
