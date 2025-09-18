-- Insert test Opportunities into SF.dbo.Opportunity
INSERT INTO SF.dbo.Opportunity (Cognizant_Synergy_WinZone_Opportunity_ID_c, Contract_Classification)
VALUES 
('4000005551', 'Sensitive - UK Citizens'),
('4000005552', 'Unrestricted'),
('4000005553', 'Sensitive - US Citizens'),
('4000005554', 'Sensitive - US Persons'),
('4000005555', 'Sensitive - UK Citizens'),
('4000005556', 'Sensitive - UK Persons'),
('4000005557', 'Unrestricted'),
('4000005558', 'Sensitive - US Citizens'),
('4000005559', 'Sensitive - UK Persons'),
('4000005560', 'Sensitive - US Persons');

-- Insert test Opportunities into Cognizant.dbo.Opportunity
INSERT INTO Cognizant.dbo.Opportunity (Opportunity_ID, Customer_ID, Sales_Stage)
VALUES
('4000005551', '1234551', 'Won'),
('4000005552', '1234552', 'Won'),
('4000005553', '1234553', 'Won'),
('4000005554', '1234554', 'Won'),
('4000005555', '1234555', 'Won'),
('4000005556', '1234556', 'Won'),
('4000005557', '1234557', 'Won'),
('4000005558', '1234558', 'Won'),
('4000005559', '1234559', 'Won'),
('4000005560', '1234560', 'Won');

-- Insert test Projects into Cognizant.dbo.Projects
INSERT INTO Cognizant.dbo.Projects (Project_ID, Project_Name, Customer_ID)
VALUES
('1000123451', 'Test Project 1', '1234551'),
('1000123452', 'Test Project 2', '1234552'),
('1000123453', 'Test Project 3', '1234553'),
('1000123454', 'Test Project 4', '1234554'),
('1000123455', 'Test Project 5', '1234555'),
('1000123456', 'Test Project 6', '1234556'),
('1000123457', 'Test Project 7', '1234557'),
('1000123458', 'Test Project 8', '1234558'),
('1000123459', 'Test Project 9', '1234559'),
('1000123460', 'Test Project 10', '1234560');
