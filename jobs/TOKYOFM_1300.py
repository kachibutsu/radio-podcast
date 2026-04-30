import sys
sys.path.append(r"C:\radio-podcast")
import pipeline

pipeline.CONFIG["station"] = "FMT"
pipeline.CONFIG["duration"] = 1830
pipeline.CONFIG["auto_git_push"] = True
pipeline.CONFIG["program_name"] = "めるる"
pipeline.main()