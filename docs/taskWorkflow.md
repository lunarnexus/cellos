
- Task is created by human and tagged as "cellos"
- cellos picks up tasks tagged as "cellos" and analyzes
  - If task has no parent, assign to architect for decomposition/planning
  - If task has assignee (architect, engineer, tester??) 
    - check for "unprocessed" status do not process tasks over and over
      - if assignee=architect, propose initial decomposition plan, or revise decomposition plan, mark status as processed.  

        Decomposition plan can be to create new tasks of type research, plan, execute, or test.  No execution tasks or task creation tasks can be done without approval status.  
      - if assignee=engineer tasks should be research or execute (should we allow Architect to do research directly?).  Execute tasks cannot be executed without approved status.  Research tasks can be "auto-approved" in config.    
      - Execute tasks are executed if approved, report status when complete

- Heartbeat scans all tasks to see if anything needs to be acted on (planning, researching, executing, task creation, testing, checking long running tasks past a timeout value)

- Task status is updated in the DB and whatever task UI (Trello, Assana, etc.) we're using.  
