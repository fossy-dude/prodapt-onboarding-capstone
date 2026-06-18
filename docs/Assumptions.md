1. CDR is assumed to be the input of the real-time pipeline. All steps before this (Charging and Rating) are not assumed to be part of scope (*per discussion with Vijay*)
2. Plans:
   1. Would include both unlimited (data, calls) as well as `talktime balance` type plans (for effecting rating and charging)
   2. Prepaid plans only (not postpaid). Outlined in problem statement (`Real-time rating and charging: track voice, data, and SMS usage and deduct corresponding charges from the subscriber's prepaid balance instantly`)
3. USSD: Will assume that the scope includes handling REST API callbacks from the telecom operator when the user interacts using the USSD system (Our system will receive the subscriber phone number, button pressed and session id). The text responses from our endpoint will be shown to the user for further interactions
4. `Multi-agent orchestration for charging, balance management, fraud detection, and subscriber support.` Also, `Agent-to-agent communication between rating engine, fraud detection, and notification agents. `
   1. This is conflicting with original requirement (CDR is created after charging, and CDR is the input). Also, Given the latency requirements (<200 ms for charging), scale (100K CDS per sec), it is not advisable to use agents for real-time charging, balance mgmt & notifications (too costly, unpredictable and slow)
   2. Assumptions:
	  1. Once a CDR event is received, after balance mgmt (deterministic), Fraud detection is executed and is powered by an agent as part of the processing pipeline. This agent will interact with the `notification tool` to send alerts to a supervisor in the fraud team. To make this scale, anomaly & Fraud detection will be handled using a rule based screening first, and this would route to Agent if risk identified for further analysis (ML classification models could be introduced in the future along with rule based decisioning)
	  2. `Subscriber support` agent will interact with a `rating agent` to understand reasons for a costing, and a separate `Balance Management` agent to address queries related to balances.
5. Requirement: `User management with subscriber account creation, SIM activation etc`
   1. For users whose sim is not activated, login will be enabled through a `Subscriber Registration ID` received after submitting a sign-up form (online) for subscriber account creation.
   2. The steps involved in a account order fulfilment flow will be simulated on the UI, concluding with an `Activated` (Ready to Use) status
6. RAG assistant will need to address general FAQ queries about the telecom provider in addition to plan/billing related queries for a more cohesive experience
7. Requirement: `real-time inventory of plan stock and provisioning state for operations teams`
   1. Assmption: Along with forecasts, show the current subscriber counts across plans along with the a view of statuses across the order fulfilment cycle in the Ops dashboard
8. 2 architectures will be proposed:
   1. `Target State` architecture: Full fledged production system capable of meeting all the functional & non-functional requirements
   2. `MVP` architecture: Proof of concept architecture meeting all the functional requirements in a limited infra environment, with a clear path to production
9. Indian telecom operator serving Indian customers only