# mail2github
Send E-Mail and create files in Github with content from the mail

## How to start?
1. Get an email you can send things to. Keep the email adress private and secure  
2. Get connection parameters for the email provider (impap server name etc.)
3. Create a github repo
4. Get the github api token
5. Fill the .env with this data
6. Use pip to install requirements.txt
7. start a cron mith mail2github.py
8. send an email (for security reasin from the target email adress itself)

This will read the emails and commit the email body to the github repo provided. There are contol markers you can use in the email subject:

## E-Mail subject

The following control markers can be used in the email subject to specify metadata for creating or updating files in the GitHub repository. These control markers are optional, and you can combine them flexibly:

1. **[commit_msg:<Commit Message>]**  
   - Example: `[commit_msg:Initial Commit]`
   - This control marker allows you to specify the commit message used for the Git commit. If no message is provided, a default message will be used: "Automatically generated change".

2. **[branch:<Branch Name>]**  
   - Example: `[branch:feature/update-file]`
   - This control marker lets you define the target branch where the changes will be committed. If no branch is specified, the default branch (e.g., `main`) will be used.

3. **[author:<Author Name>]**  
   - Example: `[author:John Doe]`
   - This control marker allows you to specify the name of the author making the change. Currently, this is only for documentation purposes and is not directly used in the code, but it may be useful for future features.

4. **[repo:<Repository Name>]**  
   - Example: `[repo:username/another-repository]`
   - This control marker allows you to specify the GitHub repository where the file should be uploaded. If no repository is specified, the default repository defined in the environment variables will be used.

5. **[tag:<Tag Name>]**  
   - Example: `[tag:v1.0.0]`
   - This control marker allows you to set a tag for the current commit. A Git tag will be created with the given name after the commit, which can be useful for versioning and releases.

6. **Path and Filename**  
   - Example: `foldername/filename.txt`
   - This is the path within the repository and the filename of the file. This is the only required field in the subject. If no path is specified, the file will be placed in the root folder of the repository.

### Examples of Complete Email Subjects:

1. **Only Path and Filename (Mandatory)**  
   - `Folder1/file.txt`
   - This places `file.txt` in the `Folder1` subfolder.

2. **Path and Filename with Commit Message and Branch**  
   - `[commit_msg:Added new feature] [branch:feature/branch-name] Folder1/file.txt`
   - This places `file.txt` in the branch `feature/branch-name` and uses the commit message "Added new feature".

3. **Filename without Path (Root of the Repository)**  
   - `[branch:main] file.txt`
   - This places `file.txt` in the root of the repository in the `main` branch.

4. **Path and Filename with All Options**  
   - `[commit_msg:Bug fix] [branch:hotfix] [author:John Doe] [repo:username/project-repo] [tag:v1.0.1] Folder2/bugfix.txt`
   - This places `bugfix.txt` in the `Folder2` subfolder of the repository `username/project-repo`, in the branch `hotfix`, with the commit message "Bug fix" and the author "John Doe", and creates the tag `v1.0.1`.

The control markers are all optional, except for the filename (and optionally the path). If you choose the root of the repository as the target, you only need to provide the filename. The control markers give you the flexibility to define the desired parameters for making changes and keep control over the Git operations.
