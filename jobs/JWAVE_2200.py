import sys
sys.path.append(r"C:\radio-podcast")
import pipeline

pipeline.CONFIG["station"] = "FMJ"
pipeline.CONFIG["duration"] = 7360
pipeline.CONFIG["auto_git_push"] = True
pipeline.CONFIG["program_name"] = "GURUGURU"
pipeline.main()