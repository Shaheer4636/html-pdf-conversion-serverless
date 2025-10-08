resources:
  repositories:
    - repository: templates
      type: git
      name: DEVOPS_Platform_as_a_Service/deploy-templates
      ref: refs/tags/7.7.0
    - repository: s3
      type: git
      name: DEVOPS_Platform_as_a_Service/s3
      ref: refs/tags/4.2.0
    - repository: iam-controls
      type: git 
      name: DEVOPS_Platform_as_a_Service/iam-controls
      ref: refs/tags/2.16.0


trigger: none

parameters:
- name: sandbox
  displayName: Deploy S3 to SAMC
  type: boolean
  default: true
- name: terrformPLANonly
  displayName: tfPlanOnly (check == true)
  type: boolean
  default: false

stages:
- template: deploy/tf-create-infra-template.yml@templates
  parameters:
    environment: sandbox
    environmentDisplayName: sandbox
    tfServiceConnection: SAMCObservability-492046385895-DEVOPSIACSVCVPC-us-east-1-Infrastructure Operations
    awsServiceConnection: SAMCObservability-492046385895-DEVOPSIACSVCVPC-Infrastructure Operations
    tfVersion: 1.13.3
    reqS3Mod: true
    application: ClientUptime
    pipelineSrcDir: $(Build.Repository.Name)
    tfPlanOnly: ${{ parameters.terrformPLANonly }}
    regionName: us-east-1
    checkoutTemplate: gitCheckouts.yml
