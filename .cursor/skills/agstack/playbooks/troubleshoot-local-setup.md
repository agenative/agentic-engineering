# Troubleshoot local setup

1. Compare the discrepancy of the given setup procedure with the expectation described in agent-services/README.md.
2. Try to start a clean agent-services following the README.md described procedure. 
   - Make sure to clean up any existing monorepo containers running locally and the docker volumes. 
3. Check if agent-services and the monorepo environments are started properly.
4. Conduct an end to end test for the mentioned agent. An end to end test skills should be able to find. Otherwise, backdown to ada-e2e-test skills but exclude all environment setup procedure except seeding data.
5. If failed, use `bug-fix` playbook to fix it.
6. If no issue found, add a brief and concise comment to the JIRA ticket with a correct procedure. Point out what was missing that causing the observed issue within 2 sentenses.
   - Unless the issue description indicate that the user is using `make local` or `make run` to start the services. otherwise, always assume and advice user to follow the pure init_environment and doco path.
7. Enhance the agent-services/README.md if appropriate to provide any missing information for other develoeprs.
